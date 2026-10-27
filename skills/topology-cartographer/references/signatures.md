# Signatures

Search recipes for the sweep. Each family is **one** search: content mode, line
numbers, result cap ~200, ripgrep regex syntax. Build a family's regex by
joining (`|`) only the rows whose gate matched. Run families in parallel. Read a
≤ 30-line window only when the target is not on the hit line - or ask the
search for 1-2 lines of after-context when a call continues on the next line.

## 0. Exclusions

Pass them to the search as one negated glob, e.g.
`!**/*{_pb2.py,_pb2_grpc.py,.pb.go,.g.dart,.min.js,.map,.lock,go.sum,-lock.json,-lock.yaml}`,
and discard hits from: `service-topology/` (this skill's own output),
`node_modules vendor dist build target out bin obj .git .venv venv __pycache__
.next coverage .terraform generated gen genproto`. Test code (`test/ tests/
__tests__/ *_test.go *.spec.* *.test.* mocks/ fixtures/`) never produces edges -
a test double is not topology - but may be read to resolve a value. Lock files
list transitive dependencies, so they never open a gate.

## 1. Services and deploy config

One glob: `**/{package.json,go.mod,pyproject.toml,setup.py,requirements.txt,pom.xml,settings.gradle,settings.gradle.kts,build.gradle,build.gradle.kts,Cargo.toml,*.csproj,Gemfile,composer.json,mix.exs,Chart.yaml,Dockerfile,application.yml,application.yaml,application.properties,docker-compose*.yml,compose*.y*ml}`,
plus Kubernetes manifests (`kind: Deployment|StatefulSet|Service`, usually
under `k8s/`, `kubernetes*/`, `deploy/`, `manifests/`, `helm/`, `charts/`).
One name search over the build manifests:
`^\s*"name"\s*:|^module\s|^name\s*=|^\s*name\s*=\s*['"]|<artifactId>|rootProject\.name|spring\.application\.name|^\s+name:\s`

**Service id = the name other services use to reach it.** In order: a compose
service or Kubernetes Deployment/Service whose name matches the directory or
whose build context points at it; `spring.application.name`; the build manifest
name (`package.json` `name` without `@scope/`, last segment of a `go.mod`
`module`, `pyproject`/`setup.py`/`Cargo.toml` `name`, first `<artifactId>`
outside `<parent>`, `rootProject.name`, a `*.csproj` file name); the directory
name. A build name like `hipstershop` never beats the deployable `adservice`.

**Deploy config is read, not just searched**, when under 300 lines: every
compose service or Kubernetes workload is a deployable and its hostname. An
`image:` of postgres, mysql, mariadb, mongo, cassandra, elasticsearch,
opensearch, clickhouse, minio or localstack is a `db`/`store` node; redis,
valkey or memcached a `cache`. Brokers (kafka, redpanda, zookeeper, rabbitmq,
nats, pulsar) are not drawn - their topics and queues are. Skip rendered
bundles that duplicate per-service manifests (e.g. `release/*.yaml`).

The deepest manifest above a file owns it. Files owned by no service produce no
edges, except deploy config and IaC, which are resolved per declared workload.
Drop wrapper roots (a workspace `package.json`, a parent `pom.xml` with
`<modules>`) that own no code. A Spring module root is the directory above
`src/main/resources`.

## 2. Address sweep - the wiring, in one search

Twelve-factor systems declare who talks to whom in deploy config. Search deploy
config (compose, Kubernetes, Helm values, `.env*`) with 1 line of after-context:

`\b[A-Z][A-Z0-9_]*_(ADDR|ADDRESS|URL|URI|HOST|HOSTNAME|ENDPOINT|DSN|BROKERS?|TOPIC|QUEUE)\b`

Each hit is `workload → VAR → value`. Map the value's host to a service,
store, external domain or broker. Then one search for all the variable names
across code finds where each is read (`os.Getenv("VAR")`, `mustMapEnv(…,
"VAR")`, `process.env.VAR`, `Configuration["VAR"]`, `@Value("${VAR}")`). An
edge needs both ends: the client call that uses the address (§3-§5), plus this
chain as supporting receipts. A variable that is declared but never read is
not an edge. A variable that is read but never declared is a `G` line.

## 3. Messaging

Gate - files-only search over manifests and imports:
`(?i)kafka|sarama|franz-go|confluent|faust|redpanda|amqp|rabbit|pika|bunny|masstransit|sqs|sns|eventbridge|kinesis|pubsub|nats|servicebus|eventhub|pulsar|bullmq|celery|sidekiq|spring-cloud-stream|xadd`

| Broker (gate) | Produce | Consume |
|---|---|---|
| Kafka (`kafka sarama franz confluent faust redpanda`) | `[Kk]afkaTemplate\.send\|KafkaTemplate<\|new ProducerRecord\|@SendTo\(\|\.to\("\|[Pp]roducer\w*\.(send\|produce\|send_and_wait)\(\|\.produce\(\|sendBatch\(\|kafka\.Message\{\|WriterConfig\{\|ProducerMessage\{\|StreamBridge\|ClientKafka` | `@KafkaListener\|@StreamListener\|KafkaConsumer\(\|AIOKafkaConsumer\(\|\.subscribe\(\s*(\{\|\[\|List\.of\|Arrays\.asList\|Collections\.singleton\|Pattern\.compile\|['"])\|ReaderConfig\{\|ConsumePartition\(\|\.Consume\(ctx\|builder\.stream\(\|@EventPattern\|@MessagePattern\|@app\.agent\|app\.topic\(` |
| RabbitMQ (`amqp rabbit pika bunny masstransit`) | `convertAndSend\(\|basic_publish\(\|basicPublish\(\|sendToQueue\(\|channel\.publish\(\|\.Publish(WithContext)?\(ctx\|\.Publish<` | `@RabbitListener\|basic_consume\(\|basicConsume\(\|channel\.consume\(\|\.Consume\(\|IConsumer<\|queue_bind\(\|QueueBind\(\|bindQueue\(\|@QueueBinding` |
| AWS (`sqs sns eventbridge kinesis`) | `SendMessage(Batch)?(Command)?\(\|send_message(_batch)?\(\|sendMessage\(\|PublishCommand\|sns\.publish\|\.publish\(\s*\{\|PutEvents(Command)?\|put_events\(\|PutRecords?(Command)?\|put_records?\(` | `ReceiveMessage(Command)?\|receive_message\(\|receiveMessage\(\|@SqsListener\|SqsMessageHandler\|GetRecords\|@KinesisListener` |
| GCP Pub/Sub (`pubsub`) | `\.topic\([^)]*\)\.publish\|topic\.Publish\(\|publisher\.publish\(\|\.publishMessage\(` | `\.subscription\(\|Subscription\(\|subscriber\.subscribe\(\|\.Receive\(ctx` |
| NATS (`nats`) | `\.[Pp]ublish\(\s*['"]\|js\.Publish\|nc\.Publish` | `\.Q?[Ss]ubscribe\(\s*['"]\|js\.(Pull)?Subscribe\|nc\.Q?Subscribe` |
| Azure (`servicebus eventhub`) | `createSender\(\|CreateSender\(\|send_messages\(\|SendMessageAsync\|EventHubProducerClient` | `createReceiver\(\|CreateProcessor\(\|ServiceBusProcessor\|EventProcessorClient` |
| Redis streams, jobs (`xadd bullmq celery sidekiq`) | `\.xadd\(\|XAdd\(\|new Queue\(\s*['"]\|\.delay\(\|apply_async\(\|send_task\(\|perform_async\(` | `\.xreadgroup\(\|XReadGroup\(\|new Worker\(\s*['"]\|@shared_task\|@\w+\.task\|Sidekiq::(Worker\|Job)` |

Escaped `\|` above are table pipes - write a plain `|` in the search.

Reading a hit: the **channel** is the first string argument, a
`topic`/`Topic`/`topics`/`destination`/`QueueUrl`/`TopicArn` field, or the
annotation value; a queue URL or ARN becomes its last segment. **Labels**:
`key=` from `key=`/`Key:` or the middle of `kafkaTemplate.send(topic, key,
value)`; `group=` from `groupId`/`group_id`/`GroupID`; `rk=` for a RabbitMQ
routing key. A bare `x.send(`/`.publish(` counts only when `x` is declared or
built as a producer client in that file - `requests`, sockets and `res.send` are
not topics. `.subscribe(` with a lambda or `{ next:` is RxJS. NestJS
`.emit('t')` counts only in a file injecting `ClientKafka`/`ClientProxy`.

**Config-declared bindings.** Spring Cloud Stream
`spring.cloud.stream.bindings.<name>.destination: <topic>`: `-out-`, `output`,
`producer`, `supplier`, `source` → pub; `-in-`, `input`, `consumer`, `sink`,
`listener` → sub; anything else is skipped. **RabbitMQ** publishers name an
exchange (topic node, label `rk=`), consumers name a queue: draw the consumer
`sub` the exchange (label `queue=…`) when a binding joins them; otherwise `sub`
the queue node and add a `G` line for the missing binding. **IaC**:
`resource "kafka_topic"|KafkaTopic|aws_sqs_queue|aws_sns_topic|AWS::SQS::Queue|AWS::SNS::Topic|google_pubsub_(topic|subscription)|azurerm_servicebus_(queue|topic)`
→ `N` lines; an SNS-to-SQS subscription is `E <topic> pub <queue>`.

## 4. Sync calls

**HTTP, GraphQL, WebSocket, vendor SDKs** - always run:
`requests\.(get|post|put|patch|delete|request)\(|httpx\.|aiohttp\.|session\.(get|post|put|patch|delete)\(|axios(\.\w+)?\(|\bfetch\(|\bgot(\.\w+)?\(|superagent|\bky\.|HttpClient|RestTemplate|restTemplate\.|WebClient|RestClient|@FeignClient|@HttpExchange|@RegisterRestClient|Request\.Builder\(\)|http\.(Get|Post|Head|PostForm|NewRequest(WithContext)?)\(|resty\.|\.R\(\)\.|Faraday|Net::HTTP|HTTParty|Guzzle|curl_init|reqwest::|GraphQLClient|ApolloClient|graphql-request|new WebSocket\(|baseURL\s*:|BaseAddress\s*=|base_url\s*=|\.baseUrl\(|new Stripe\(|OpenAI\(|Anthropic\(|GenerativeAI\(|genai\.Client|Twilio\(|SendGridAPIClient`

**gRPC contracts** - over `*.proto` only: `^\s*service\s+\w+\s*\{`. Copies of
one contract in several directories count once; cite the shallowest.

**gRPC code** - excluding `*.proto` and generated stubs:
`Register\w+Server\(|add_\w+Servicer_to_server|\w+Grpc\.\w+ImplBase|MapGrpcService<|\.addService\(|\w+Stub\(|new(Blocking|Future)?Stub\(|New\w+Client\(\s*[\w.]*(conn|Conn|cc)\b|\.\w+Client\(\s*channel|credentials\.create(Insecure|Ssl)\(|@GrpcClient|grpc\.(insecure_channel|Dial|NewClient)\(`

**HTTP target.** The URL is a literal, a template (`${BASE}/orders/${id}`), a
concatenation (`BASE + "/orders/" + id`), or a client base URL. Its host becomes:

- a service id or deployable hostname (compose, Kubernetes, OpenAPI `servers`)
  → that service, `CODE`;
- a public domain → an `ext` node, `CODE`. A vendor SDK client is an `ext` node
  named after the vendor (`stripe`, `openai`, `gemini`), `CODE`;
- `localhost`, `127.0.0.1`, `0.0.0.0`, `[::]`, `host.docker.internal`,
  `example.*` → skipped (local test clients are not topology);
- a bare host matching nothing → a `ref` node, `INFERENCE`;
- no host, only a path → match route declarations (OpenAPI `paths`,
  `@GetMapping`, `app.get(`, `HandleFunc(`, `@app.route`). One match →
  `INFERENCE` with the route as supporting receipt; none → drop and add a `G`.

Labels are `METHOD /path`: ids become `{id}`, query strings are dropped. Feign
interfaces: one label per `@*Mapping`, up to 6 per pair, then `+N more`.
Server-side routes are not edges; they make path matching possible.

**gRPC target.** A contract `service X` is owned by the service that registers
it (`RegisterXServer`, `add_XServicer_to_server`, `XImplBase`,
`MapGrpcService<X>`, `addService(…X.service`). A stub or client for X elsewhere
→ `E caller grpc owner`, labelled with the RPCs called (often on the next
line). `CODE` if a registration was found; `INFERENCE` if only the contract's
directory suggests the owner; no contract → `ref` node named X, `INFERENCE`. An
address from §2 resolves the owner like an HTTP host. A file calling its own
server is not an edge.

## 5. Datastores

`(postgres(ql)?|mysql|mariadb|sqlserver|oracle|mongodb(\+srv)?|cassandra|clickhouse|elasticsearch|opensearch|redis|rediss|valkey|memcached|neo4j|s3)://|jdbc:\w+:|sql\.Open\(|gorm\.Open\(|pgx(pool)?\.(Connect|New)|create_engine\(|mongoose\.connect|MongoClient\(|new Redis\(|redis\.(Redis|StrictRedis|from_url|createClient|NewClient)\(|createClient\(\s*\{\s*url|AddStackExchangeRedisCache|ConnectionMultiplexer|Jedis|LettuceConnection|DynamoDB|S3Client|boto3\.(client|resource)\(\s*['"](s3|dynamodb)|bigquery\.(NewClient|Client)\(|firestore\.(NewClient|Client)\(|spanner\.NewClient|SpannerConnection\b|AlloyDBEngine|alloydbconn|CosmosClient|BlobServiceClient|spring\.datasource\.url|ConnectionStrings`

The node is the connection host - often only visible through §2 (`REDIS_ADDR:
redis-cart:6379`). A host naming a deployable reuses that node and its kind. A
numeric path (`redis://cache:6379/0`) is an index, not a name. Label the edge
with the engine (`sql`, `redis`, `mongo`, `s3`) - never copy a connection
string or credential into a label or note. `amqp://` and `nats://` are
brokers, not stores. Compose `depends_on` is a `dep` edge only when no stronger
edge joins the pair - otherwise it is a supporting receipt.

**Optional backends.** A store or client chosen by a config flag (`if
os.Getenv("X") != ""`, a DI switch) is still an edge: label it `optional: X`
and note what it replaces.

## 6. Resolution ladder - first hit wins

1. Literal at the call site → `CODE`.
2. Same-file constant or env default (`os.environ.get("K", "v")`,
   `process.env.K ?? 'v'`, `${K:v}`, `@Value("${k:v}")`, `const X = '…'`) →
   `CODE`; add the defining line as a receipt.
3. Config value: search the key across
   `**/*.{yml,yaml,properties,env,tf,tfvars,toml,json}` and `**/.env*` as
   written, as `SHOUTY_SNAKE`, as `dotted.lower`, by its last dotted segment
   (`INFRA.KAFKA.TOPICS.REFUND` → `REFUND`) and camel → snake
   (`refundTopic` → `REFUND_TOPIC`). One value → `CODE` with the config line as
   a receipt. Values differing per environment → use the base file, note the rest.
4. Cross-file constant - search `\bSYMBOL\b\s*[:=]` repo-wide. Exactly one
   definition → `CODE` with the chain in receipts; several → `INFERENCE`
   naming them.
5. Project wrapper (`this.events.publish(TOPIC)`, `IPubSubService.subscribe`) →
   open the wrapper once, confirm it delegates to a real client, then treat its
   call sites as that client. Receipts: call site, then the delegation line.
6. Named but unresolvable (`${KEY}` with no value in the repo, a deploy-time
   variable) → topic/queue: `INFERENCE` edge to node `KEY?`; HTTP or gRPC: a
   `G` line, no edge.
7. Computed at runtime (`topicFor(tenant)`, a URL read from a database) → no
   edge; a `G` line naming the function.

A channel name must match `[A-Za-z0-9][A-Za-z0-9._-]*`. Numbers, booleans,
class names (`StringSerializer`), paths and sentences are rejected.

## 7. Adding an ecosystem

Add one row here, a snippet to a fixture under `examples/`, and its expected
lines to that fixture's ledger. There is no code to change.
