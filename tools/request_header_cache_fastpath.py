from pathlib import Path
p=Path('night.py')
text=p.read_text(encoding='utf-8')
text=text.replace("    _header_cache: dict[str, str | None] = dataclasses.field(default_factory=dict, init=False)\n", "    _header_cache: dict[str, str | None] | None = dataclasses.field(default=None, init=False)\n", 1)
old='''        if key in self._header_cache:\n            value = self._header_cache[key]\n            return default if value is None else value\n\n        target = key.encode("latin-1")\n'''
new='''        cache = self._header_cache\n        if cache is not None and key in cache:\n            value = cache[key]\n            return default if value is None else value\n\n        target = key.encode("latin-1")\n'''
if old not in text: raise SystemExit('header cache read anchor missing')
text=text.replace(old,new,1)
old='''        self._header_cache[key] = value\n        return default if value is None else value\n'''
new='''        if cache is None:\n            cache = {}\n            self._header_cache = cache\n        cache[key] = value\n        return default if value is None else value\n'''
if old not in text: raise SystemExit('header cache write anchor missing')
text=text.replace(old,new,1)
p.write_text(text,encoding='utf-8')
