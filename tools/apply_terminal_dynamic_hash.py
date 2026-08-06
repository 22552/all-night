from pathlib import Path

p = Path('night.py')
s = p.read_text()

s = s.replace(
'''        self._dynamic_prefix_index: dict[str, dict[str, list[Route]]] = {}\n        self._static_method_index: dict[str, dict[str, Route]] = {}\n''',
'''        self._dynamic_prefix_index: dict[str, dict[str, list[Route]]] = {}\n        self._dynamic_terminal_index: dict[str, dict[str, Route]] = {}\n        self._static_method_index: dict[str, dict[str, Route]] = {}\n''', 1)

s = s.replace(
'''                if route._night_simple_dynamic is not None:\n                    prefix = route._night_simple_dynamic[0]\n                    self._dynamic_prefix_index.setdefault(method, {}).setdefault(prefix, []).append(route)\n                self._rebuild_dynamic_matcher(method)\n''',
'''                if route._night_simple_dynamic is not None:\n                    prefix, suffix, _name, _converter = route._night_simple_dynamic\n                    self._dynamic_prefix_index.setdefault(method, {}).setdefault(prefix, []).append(route)\n                    if not suffix and prefix.endswith("/"):\n                        base = prefix[:-1] or "/"\n                        self._dynamic_terminal_index.setdefault(method, {})[base] = route\n                self._rebuild_dynamic_matcher(method)\n''', 1)

s = s.replace(
'''        self._dynamic_method_matchers.clear()\n        self._dynamic_prefix_index.clear()\n        self._static_method_index.clear()\n''',
'''        self._dynamic_method_matchers.clear()\n        self._dynamic_prefix_index.clear()\n        self._dynamic_terminal_index.clear()\n        self._static_method_index.clear()\n''', 1)

old = '''        else:\n            prefixed = self._match_prefixed_dynamic(key, method)\n            if prefixed is not None:\n                return prefixed\n\n            # Generic fallback only for complex/multi-parameter routes.\n'''
new = '''        else:\n            terminal = self._dynamic_terminal_index.get(method)\n            if terminal:\n                base, sep, value = key.rpartition("/")\n                if sep and value:\n                    route = terminal.get(base or "/")\n                    if route is not None:\n                        _prefix, _suffix, name, converter = route._night_simple_dynamic\n                        if converter == "int":\n                            try:\n                                value = int(value)\n                            except ValueError:\n                                route = None\n                        if route is not None:\n                            return route, {name: value}\n\n            prefixed = self._match_prefixed_dynamic(key, method)\n            if prefixed is not None:\n                return prefixed\n\n            # Generic fallback only for complex/multi-parameter routes.\n'''
if old not in s:
    raise SystemExit('match anchor missing')
s = s.replace(old, new, 1)

p.write_text(s)
