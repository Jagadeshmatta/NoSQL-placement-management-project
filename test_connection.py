import os
from pymongo import MongoClient
from neo4j import GraphDatabase

try:
    client = MongoClient(os.environ["MONGO_URI"], serverSelectionTimeoutMS=8000)
    client.admin.command("ping")
    print("MongoDB connected")
except Exception as e:
    print("MongoDB FAILED:", e)

try:
    driver = GraphDatabase.driver(
        os.environ["NEO4J_URI"],
        auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]))
    driver.verify_connectivity()
    with driver.session(database=os.environ.get("NEO4J_DATABASE")) as s:
        count = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
    print("Neo4j connected, nodes in graph:", count)
except Exception as e:
    print("Neo4j FAILED:", e)