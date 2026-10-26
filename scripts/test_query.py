from neo4j import GraphDatabase

# 连接配置
uri = "bolt://localhost:7687"
username = "neo4j"
password = "wr20021218"

# 创建驱动
driver = GraphDatabase.driver(uri, auth=(username, password))

# 执行查询
with driver.session() as session:
    result = session.run("MATCH (m:Material) RETURN m.name LIMIT 5")
    for record in result:
        print(record["m.name"])

# 关闭连接
driver.close()
