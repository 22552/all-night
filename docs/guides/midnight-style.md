# Midnight style API

Midnight exposes a small browser-side styling API through `window.midnight`. It is intentionally CSS-first: it changes presentation without giving the styling helpers responsibility for application state or HTML generation.

## Inline styles

Use `midnight.style(selector, styles)` to apply CSS properties to every matching element:

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

Both JavaScript property names and CSS property names are accepted. CSS custom properties are supported too:

```js
midnight.style(":root", {
  "--accent": "hotpink",
  "font-family": "system-ui",
});
```

Pass `null` or `undefined` for a property to remove that inline style.

The function returns the number of matched elements.

## Show, hide, and toggle

```js
midnight.hide("#debug-panel");
midnight.show("#debug-panel");
midnight.toggle("#debug-panel");
```

`hide()` stores the element's previous inline `display` value before setting `display: none`. `show()` restores that value when possible. If the element is still hidden by stylesheet rules, `show()` falls back to `display: block`.

You can force a display mode:

```js
midnight.show("#toolbar", "flex");
midnight.toggle("#advanced", true, "grid");
```

The second argument to `toggle()` is an optional force flag. `true` shows, `false` hides, and `null`/omitted toggles the current computed visibility.

## Arbitrary CSS

For full CSS control, use `midnight.css(cssText, id)`:

```js
midnight.css(`
  #sidebar { display: none; }
  #main { width: 100%; }
  .card { border-radius: 0; }
`, "layout");
```

Midnight creates a `<style>` element in the document head. Calling `midnight.css()` again with the same ID replaces its contents instead of creating another stylesheet:

```js
midnight.css("#main { max-width: 900px; }", "layout");
```

The default ID is `"default"`.

To clear a named stylesheet while keeping its style node:

```js
midnight.css("", "layout");
```

## Scope and security

These APIs run entirely in the browser. They do not send a Midnight event to the server and do not require a WebSocket connection.

`midnight.css()` accepts arbitrary CSS by design. Only feed it CSS that your application trusts. CSS cannot execute normal JavaScript, but it can substantially alter what users see, hide controls, load referenced resources through CSS URLs, or otherwise change presentation. Do not treat user-supplied CSS as a security boundary.

## API summary

```text
midnight.style(selector, styles)          -> number of matched elements
midnight.hide(selector)                   -> number of matched elements
midnight.show(selector, display?)         -> number of matched elements
midnight.toggle(selector, force?, display?) -> number of matched elements
midnight.css(cssText, id?)                -> HTMLStyleElement
```
