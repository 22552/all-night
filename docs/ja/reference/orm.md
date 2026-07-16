# SQLite ORM

`Database` は依存なしの小さな同期SQLite ORMです。小規模アプリや試作向けで、非同期クエリ・マイグレーション・複数プロセス間の整合性が必要なら外部のDBレイヤーを利用してください。

```python
from night import Database

db = Database("app.db")

@db.model
class User:
    name: str
    active: bool

db.create_all(User)

user = User.create(name="Ada", active=True)
same_user = User.get(user.id)
active_users = User.filter(active=True)

same_user.name = "Ada Lovelace"
same_user.save()
same_user.delete()
```

登録後のモデルはdataclassになります。`id` は宣言しないでください。SQLiteの自動採番主キーとして作られ、insert後に属性として追加されます。

対応するカラム型は `int`、`float`、`str`、`bytes`、`bool` と、それらの `Optional[T]` です。終了時には `db.close()` を呼び、トランザクションには `with db.transaction():` を使います。


