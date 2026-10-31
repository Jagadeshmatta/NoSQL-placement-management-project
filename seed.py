from app import init_graph, save_student, save_company

init_graph()
save_student("Jagadesh", "30", "CSE", 8.2, "python, java, mongodb")
save_student("Ravi", "21A01", "CSE", 8.2, "python, java, mongodb")
save_student("Sita", "21A02", "CSE", 7.0, "python, react, node.js")
save_student("Kiran", "21A03", "IT", 6.2, "java, docker")
save_student("Meena", "21A04", "ECE", 7.8, "python, sql")
save_company("TCS", "System Engineer", 6.0, "java, python")
save_company("Infosys", "Power Programmer", 7.5, "python, mongodb")
save_company("Wipro", "Web Developer", 6.5, "react, node.js")
save_company("Cognizant", "Data Analyst", 7.0, "sql, python")
print("Sample data loaded.")