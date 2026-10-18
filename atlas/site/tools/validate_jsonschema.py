"""Validate every generated /api/v1/ data file in dist/api/v1 against its JSON Schema with the standard
jsonschema library (Draft 2020-12 + FormatChecker). CI-only: install requirements-ci.txt first.

Usage: python atlas/site/tools/validate_jsonschema.py [path/to/dist/api/v1]
Exit code 1 on any error. check.py imports validator_for_dir() from here when jsonschema is installed.
"""
import json
import os
import sys

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT = os.path.join(HERE, '..', 'dist', 'api', 'v1')


def load_schemas(v_dir):
    """{file name: schema} from <v_dir>/schemas/*.schema.json."""
    sdir = os.path.join(v_dir, 'schemas')
    return {fn: json.load(open(os.path.join(sdir, fn), encoding='utf-8'))
            for fn in sorted(os.listdir(sdir)) if fn.endswith('.schema.json')}


def make_validators(schemas):
    """{file name: Draft202012Validator}; cross-file $refs resolve through each schema's $id."""
    registry = Registry().with_resources((s['$id'], Resource.from_contents(s, default_specification=DRAFT202012))
                                         for s in schemas.values())
    fc = FormatChecker()
    out = {}
    for name, s in schemas.items():
        Draft202012Validator.check_schema(s)
        out[name] = Draft202012Validator(s, registry=registry, format_checker=fc)
    return out


def errors_for(validator, obj, limit=5):
    errs = []
    for e in sorted(validator.iter_errors(obj), key=lambda e: list(e.absolute_path)):
        errs.append('$' + ''.join(f'[{p!r}]' if isinstance(p, int) else f'.{p}' for p in e.absolute_path) + ': ' + e.message[:200])
        if len(errs) >= limit:
            break
    return errs


def main(v_dir):
    v_dir = os.path.abspath(v_dir)
    if not os.path.isdir(v_dir):
        print(f'error: {v_dir} missing; run python3 atlas/site/build.py first', file=sys.stderr)
        return 1
    validators = make_validators(load_schemas(v_dir))
    fails, n = [], 0
    for root, _, files in os.walk(v_dir):
        if os.path.basename(root) == 'schemas':
            continue
        for fn in sorted(files):
            if not fn.endswith('.json'):
                continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, v_dir).replace(os.sep, '/')
            obj = json.load(open(fp, encoding='utf-8'))
            if not isinstance(obj, dict) or 'schema' not in obj:
                continue  # index.json, changelog.json, openapi.json: no data schema
            name = str(obj['schema']).rsplit('/', 1)[-1]
            if name not in validators:
                fails.append(f'{rel}: unknown schema {obj["schema"]}'); continue
            n += 1
            for err in errors_for(validators[name], obj):
                fails.append(f'{rel} ({name}): {err}')
    for f in fails:
        print('FAIL', f)
    if n == 0:
        print('FAIL no data documents found', file=sys.stderr)
        return 1
    from importlib.metadata import version
    print(f'jsonschema {version("jsonschema")}: {n} API v1 data files validated (Draft 2020-12 + formats), {len(fails)} errors')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))
