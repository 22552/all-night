# Midnight Style API

Midnight は `window.midnight` から、ブラウザ側だけで使えるスタイル操作APIを公開します。テーマ設定に限定せず、CSSを自由に変更するための低レベルAPIです。

## インラインスタイル

`midnight.style(selector, styles)` は、セレクタに一致するすべての要素へCSSを適用します。

```html
<script src="/midnight.js"></script>
<script>
midnight.style("#panel", {
  display: "grid",
  gridTemplateColumns: "1fr 2fr",
  gap: "12px",
  backgroundColor: "#111",
});
</script>
```

JavaScript形式のプロパティ名とCSS形式のプロパティ名の両方を使えます。CSSカスタムプロパティも利用できます。

```js
midnight.style(":root", {
  "--accent": "hotpink",
  "font-family": "system-ui",
});
```

値に `null` または `undefined` を指定すると、そのインラインスタイルを削除します。

戻り値は一致した要素数です。

## show / hide / toggle

```js
midnight.hide("#debug-panel");
midnight.show("#debug-panel");
midnight.toggle("#debug-panel");
```

`hide()` は元のインライン `display` 値を保存してから `display: none` にします。`show()` は可能ならその値を復元します。スタイルシート側でまだ非表示になる場合は `display: block` にフォールバックします。

表示方式を明示することもできます。

```js
midnight.show("#toolbar", "flex");
midnight.toggle("#advanced", true, "grid");
```

`toggle()` の第2引数は任意のforce値です。`true` なら表示、`false` なら非表示、省略または `null` なら現在のcomputed styleからトグルします。

## CSSを丸ごと自由に変更

完全に自由なCSSを入れたい場合は `midnight.css(cssText, id)` を使います。

```js
midnight.css(`
  #sidebar { display: none; }
  #main { width: 100%; }
  .card { border-radius: 0; }
`, "layout");
```

Midnight は `<head>` に `<style>` 要素を作成します。同じIDで再度呼び出すと、新しいstyleタグを増やさず内容だけを置き換えます。

```js
midnight.css("#main { max-width: 900px; }", "layout");
```

IDを省略した場合は `"default"` が使われます。

名前付きCSSを空にする場合:

```js
midnight.css("", "layout");
```

## サーバー通信との関係

これらのAPIは完全にブラウザ内で実行されます。Midnightイベントをサーバーへ送らず、WebSocket接続も必要ありません。

つまり次のような用途に向いています。

```js
midnight.hide("#sidebar");
midnight.show("#experimental", "flex");
midnight.style("#main", { width: "100vw" });
midnight.css("button { border-radius: 999px; }", "buttons");
```

## セキュリティ

`midnight.css()` は仕様として任意CSSを受け取ります。アプリケーションが信頼できるCSSだけを渡してください。

CSSは通常のJavaScriptを直接実行するものではありませんが、UIを隠したり見た目を大きく変えたり、CSS URL経由で外部リソースを参照したりできます。ユーザー入力CSSをセキュリティ境界として扱わないでください。

## API一覧

```text
midnight.style(selector, styles)            -> 一致した要素数
midnight.hide(selector)                     -> 一致した要素数
midnight.show(selector, display?)           -> 一致した要素数
midnight.toggle(selector, force?, display?) -> 一致した要素数
midnight.css(cssText, id?)                  -> HTMLStyleElement
```
