# SQLite ORM

`Database` is Night's deliberately small synchronous SQLite ORM. It is suitable for small applications and prototypes; use an external database layer when asynchronous queries, migrations, or multiple-process coordination are required.

```python
from night import Database

db = Database("app.db")

@db.model
class User:
    name: str
    active: bool

db.create_all(User)

user = User.create(name="Ada", active=True)
assert user.id is not None

same_user = User.get(user.id)
active_users = User.filter(active=True)

same_user.name = "Ada Lovelace"
same_user.save()
same_user.delete()
```

Models are dataclasses after registration. Do not declare `id`: Night creates an SQLite autoincrement primary key and attaches `id` after insertion.

Supported column annotations are `int`, `float`, `str`, `bytes`, `bool`, and `Optional[T]` for those types. Call `db.close()` during application shutdown. `with db.transaction():` groups changes into a transaction.


