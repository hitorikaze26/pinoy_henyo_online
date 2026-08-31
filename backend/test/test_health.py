from app import create_app


def test_health_returns_200():
    app = create_app("testing")
    with app.test_client() as client:
        response = client.get("/api/health")
        assert response.status_code == 200
        body = response.get_json()
        assert body["success"] is True
        assert body["message"] == "Pinoy Henyo Online API is running"


def test_database_health_returns_ok():
    app = create_app("testing")
    with app.test_client() as client:
        response = client.get("/api/health/db")
        assert response.status_code == 200
        body = response.get_json()
        assert body["success"] is True
        assert body["message"] == "Database connection is healthy"


def test_unknown_route_returns_404_json():
    app = create_app("testing")
    with app.test_client() as client:
        response = client.get("/api/nonexistent")
        assert response.status_code == 404
        body = response.get_json()
        assert body["success"] is False
        assert body["error"]["code"] == "NOT_FOUND"