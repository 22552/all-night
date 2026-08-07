# Model Context Protocol (MCP)

Night は既存の RPC registry を、HTTP 上の stateless **MCP 2026-07-28** tool server として公開できます。

MCP 実装は `night_mcp.py` に分離されているため、`night.py` の単一ファイル・依存なしのコア設計は維持されます。

## MCPを有効化する

```python
from night import Night
from night_mcp import enable_mcp

app = Night()
mcp = enable_mcp(app, path="/mcp", name="my-night-service")

@mcp.tool(description="2つの整数を足す")
def add(a: int, b: int):
    return {"value": a + b}
```

既存の `@app.rpc(...)` も自動的に MCP tool として公開されます。

```python
@app.rpc("echo")
def echo(text: str):
    return {"echo": text}

enable_mcp(app)
```

## 対応範囲

現在は MCP `2026-07-28` の stateless tool server に必要なコアを実装しています。

- `server/discover`
- `tools/list`
- `tools/call`
- `MCP-Protocol-Version`
- `Mcp-Method`
- `Mcp-Name` の整合性確認
- `resultType`
- `_meta.io.modelcontextprotocol/serverInfo`
- `ttlMs` / `cacheScope`

2026-07-28 では protocol-level session と initialize handshake が不要になったため、このtransportでは `Mcp-Session-Id` を作りません。

## Tool schema

Python 関数の signature と型注釈から軽量な JSON Schema を生成します。

```python
@mcp.tool()
def search(query: str, limit: int = 10):
    ...
```

`str`、`int`、`float`、`bool`、union、list、literal、mapping、dataclass などを依存追加なしで扱います。

## Tool result

`dict` は text content に加えて `structuredContent` としても返します。文字列やscalarはtextとして返します。sync / async両方のtoolに対応します。

Tool本体で発生した例外は `isError: true` のtool resultとして返します。未知のmethod、引数不正、HTTP headerとbodyの不一致などはJSON-RPC errorになります。

## Header validation

MCP 2026-07-28 のHTTP requestでは、Nightはrouting用headerとJSON-RPC bodyの整合性を確認します。

```http
POST /mcp
MCP-Protocol-Version: 2026-07-28
Mcp-Method: tools/call
Mcp-Name: search
```

不一致の場合は MCP header mismatch code `-32020` を返します。

## Deploy

MCP endpointは通常のNight HTTP routeなので、ASGI server、Cloudflare Python Workers、Vercel Functionsの同じアプリで利用できます。

- [Cloudflare Python Workers](cloudflare-workers.md)
- [Vercel Functions](../operations/vercel.md)

## 今後

最初の実装は modern stateless tool path に絞っています。resources、prompts、Tasks、subscriptions、authorization helper、旧sessionful revision、Multi Round-Trip Requests は今後の拡張対象です。
