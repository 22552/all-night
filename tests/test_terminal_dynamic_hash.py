from night import Night


def test_terminal_dynamic_hash_selects_correct_route_and_converter():
    app = Night()
    for index in range(200):
        def endpoint(id, _index=index):
            return {"route": _index, "id": id}
        app.get(f"/dynamic/{index}/<int:id>")(endpoint)

    client = app.test_client()
    assert client.get("/dynamic/0/7").get_json() == {"route": 0, "id": 7}
    assert client.get("/dynamic/199/42").get_json() == {"route": 199, "id": 42}
    assert client.get("/dynamic/199/nope").status_code == 404
    client.close()


def test_terminal_dynamic_hash_is_method_specific():
    app = Night()

    @app.get("/items/<int:id>")
    def get_item(id):
        return {"method": "get", "id": id}

    @app.post("/items/<int:id>")
    def post_item(id):
        return {"method": "post", "id": id}

    client = app.test_client()
    assert client.get("/items/3").get_json() == {"method": "get", "id": 3}
    assert client.post("/items/3").get_json() == {"method": "post", "id": 3}
    client.close()
