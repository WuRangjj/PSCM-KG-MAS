from neo4j import GraphDatabase

# ===== 配置（改成你自己的） =====
URI = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD = "wr20021218"  #

# ===== 测试连接 =====
def test_connection():
    try:
        driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))
        with driver.session() as session:
            result = session.run("RETURN '连接成功！' AS message")
            print(result.single()["message"])
        driver.close()
        print("✅ Neo4j 连接正常！")
    except Exception as e:
        print(f"❌ 连接失败: {e}")

if __name__ == "__main__":
    test_connection()