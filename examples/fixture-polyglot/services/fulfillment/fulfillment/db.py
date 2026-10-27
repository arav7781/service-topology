from sqlalchemy import create_engine

# Reads and writes the orders service's own database.
engine = create_engine("postgresql://fulfillment:secret@orders-db:5432/orders")
