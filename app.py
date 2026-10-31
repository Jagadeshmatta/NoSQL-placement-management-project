"""College Placement Management System
Flask + MongoDB (records) + Neo4j (skill matching graph)"""
import os
from datetime import datetime
from functools import wraps

from bson import ObjectId
from flask import Flask, render_template, request, redirect, url_for, flash
from pymongo import MongoClient
from neo4j import GraphDatabase

# ---------- Database connections (read from the PowerShell variables you set) ----------
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE")

mongo = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)["placement_db"]
graph = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

app = Flask(__name__)
app.secret_key = "placement-lab"
STATUSES = ["Applied", "Shortlisted", "Interview Scheduled", "Selected", "Rejected"]

# Matching query: shared skill + student CGPA >= company minimum CGPA
MATCH_QUERY = """
MATCH (s:Student)-[:HAS_SKILL]->(sk:Skill)<-[:REQUIRES_SKILL]-(c:Company)
WHERE s.cgpa >= c.min_cgpa
RETURN s.id AS sid, s.name AS Student, c.id AS cid, c.name AS Company,
       c.role AS JobRole, collect(DISTINCT sk.name) AS MatchingSkills,
       count(DISTINCT sk) AS MatchCount
ORDER BY MatchCount DESC, Student
"""


# ---------- Helpers ----------
def cypher(query, **params):
    """Run a Cypher query on Neo4j and return the rows as dictionaries."""
    with graph.session(database=NEO4J_DATABASE) as session:
        return [r.data() for r in session.run(query, **params)]


def init_graph():
    """Unique constraints so students, companies and skills are never duplicated."""
    cypher("CREATE CONSTRAINT student_id IF NOT EXISTS FOR (s:Student) REQUIRE s.id IS UNIQUE")
    cypher("CREATE CONSTRAINT company_id IF NOT EXISTS FOR (c:Company) REQUIRE c.id IS UNIQUE")
    cypher("CREATE CONSTRAINT skill_name IF NOT EXISTS FOR (k:Skill) REQUIRE k.name IS UNIQUE")


def skill_list(text):
    return sorted({x.strip().lower() for x in text.split(",") if x.strip()})


def number(text, label, low, high):
    try:
        value = float(text)
    except ValueError:
        raise ValueError(f"{label} must be a number.")
    if not low <= value <= high:
        raise ValueError(f"{label} must be between {low} and {high}.")
    return value


def required(form, *names):
    values = [form.get(n, "").strip() for n in names]
    if not all(values):
        raise ValueError("Please fill in all fields.")
    return values


def safe(func):
    """Show validation / database errors as a message instead of crashing."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ValueError as e:
            flash(str(e))
        except Exception as e:
            flash(f"Database error: {e}")
        return redirect(url_for("home"))
    return wrapper


# ---------- Logic that keeps MongoDB and Neo4j in sync ----------
def save_student(name, roll_no, dept, cgpa, skills_text, sid=None):
    skills = skill_list(skills_text)
    if not skills:
        raise ValueError("Enter at least one skill.")
    doc = {"name": name, "roll_no": roll_no, "department": dept, "cgpa": cgpa, "skills": skills}
    if sid is None:
        sid = str(mongo.students.insert_one(doc).inserted_id)              # MongoDB: Create
    else:
        mongo.students.update_one({"_id": ObjectId(sid)}, {"$set": doc})    # MongoDB: Update
        mongo.applications.update_many({"student_id": sid}, {"$set": {"student": name}})
    # Neo4j: create/update the student node and rebuild its skill relationships
    cypher("""MERGE (s:Student {id:$id}) SET s.name=$name, s.cgpa=$cgpa
              WITH s OPTIONAL MATCH (s)-[r:HAS_SKILL]->() DELETE r""",
           id=sid, name=name, cgpa=cgpa)
    cypher("""MATCH (s:Student {id:$id}) UNWIND $skills AS k
              MERGE (sk:Skill {name:k}) MERGE (s)-[:HAS_SKILL]->(sk)""",
           id=sid, skills=skills)
    return sid


def save_company(name, role, min_cgpa, skills_text):
    skills = skill_list(skills_text)
    if not skills:
        raise ValueError("Enter at least one required skill.")
    cid = str(mongo.companies.insert_one(
        {"name": name, "role": role, "min_cgpa": min_cgpa, "skills": skills}).inserted_id)
    cypher("""MERGE (c:Company {id:$id}) SET c.name=$name, c.role=$role, c.min_cgpa=$min
              WITH c UNWIND $skills AS k
              MERGE (sk:Skill {name:k}) MERGE (c)-[:REQUIRES_SKILL]->(sk)""",
           id=cid, name=name, role=role, min=min_cgpa, skills=skills)
    return cid


# ---------- Routes ----------
@app.route("/")
def home():
    data = dict(students=[], companies=[], matches=[], apps=[], edit=None, statuses=STATUSES)
    try:
        data["students"] = list(mongo.students.find().sort("name", 1))
        data["companies"] = list(mongo.companies.find().sort("name", 1))
        data["apps"] = list(mongo.applications.find().sort("applied_on", -1))
        if request.args.get("edit"):
            data["edit"] = mongo.students.find_one({"_id": ObjectId(request.args["edit"])})
        data["matches"] = cypher(MATCH_QUERY)
    except Exception as e:
        flash(f"Cannot reach the databases: {e}")
    return render_template("index.html", **data)


@app.route("/student/save", methods=["POST"])
@safe
def student_save():
    f = request.form
    name, roll, dept, skills = required(f, "name", "roll_no", "department", "skills")
    cgpa = number(f.get("cgpa", ""), "CGPA", 0, 10)
    sid = f.get("id") or None
    save_student(name, roll, dept, cgpa, skills, sid)
    flash("Student updated." if sid else "Student added.")
    return redirect(url_for("home"))


@app.route("/student/delete/<sid>")
@safe
def student_delete(sid):
    mongo.students.delete_one({"_id": ObjectId(sid)})                      # MongoDB: Delete
    mongo.applications.delete_many({"student_id": sid})
    cypher("MATCH (s:Student {id:$id}) DETACH DELETE s", id=sid)           # Neo4j: Delete
    flash("Student deleted from MongoDB and Neo4j.")
    return redirect(url_for("home"))


@app.route("/company/add", methods=["POST"])
@safe
def company_add():
    f = request.form
    name, role, skills = required(f, "name", "role", "skills")
    min_cgpa = number(f.get("min_cgpa", ""), "Minimum CGPA", 0, 10)
    save_company(name, role, min_cgpa, skills)
    flash("Company added.")
    return redirect(url_for("home"))


@app.route("/company/delete/<cid>")
@safe
def company_delete(cid):
    mongo.companies.delete_one({"_id": ObjectId(cid)})
    mongo.applications.delete_many({"company_id": cid})
    cypher("MATCH (c:Company {id:$id}) DETACH DELETE c", id=cid)
    flash("Company deleted from MongoDB and Neo4j.")
    return redirect(url_for("home"))


@app.route("/apply", methods=["POST"])
@safe
def apply():
    sid, cid = request.form["student_id"], request.form["company_id"]
    if mongo.applications.find_one({"student_id": sid, "company_id": cid}):
        raise ValueError("This student has already applied for this job.")
    s = mongo.students.find_one({"_id": ObjectId(sid)})
    c = mongo.companies.find_one({"_id": ObjectId(cid)})
    mongo.applications.insert_one({
        "student_id": sid, "student": s["name"], "company_id": cid,
        "company": c["name"], "role": c["role"], "status": "Applied",
        "applied_on": datetime.now().strftime("%Y-%m-%d %H:%M")})
    flash("Application saved in MongoDB.")
    return redirect(url_for("home"))


@app.route("/status/<aid>", methods=["POST"])
@safe
def status(aid):
    mongo.applications.update_one({"_id": ObjectId(aid)}, {"$set": {"status": request.form["status"]}})
    flash("Status updated.")
    return redirect(url_for("home"))


if __name__ == "__main__":
    try:
        init_graph()
    except Exception as e:
        print("Warning: could not reach Neo4j:", e)
    app.run(debug=True)