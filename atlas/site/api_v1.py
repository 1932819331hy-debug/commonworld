"""Commonworld static API v1 (/api/v1/): JSON Schemas, OpenAPI 3.1 description, changelog and a tiny JSON Schema validator.

Stdlib only. build.py writes the files; check.py validates every generated document against the schemas here.
Stability rule: within v1 only backwards-compatible changes (new optional fields, new files) bump the minor
schema_version; removing or renaming a field, changing its type or meaning, or moving a URL is a breaking change
and ships as /api/v2/ while /api/v1/ keeps working.
"""
import re

API_VERSION = 'v1'
SCHEMA_VERSION = '1.0.0'
API_BASE = '/api/v1'
STATUSES = ['live', 'closed']
ENTITY_TYPES = ['platform', 'tool_catalog', 'protocol', 'project']
BASES = ['direct_observation', 'operator_claim', 'independent_source', 'inference']
OUTCOMES = ['supported', 'contradicted', 'unchecked', 'inaccessible', 'needs_browser']
ID_PATTERN = r'^[a-z0-9][a-z0-9-]*$'
UTC_PATTERN = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?Z$'  # ISO 8601 UTC (seconds optional, as in the source claims)

# newest first; build.py writes changelog.json and CHANGELOG.md from this list
CHANGELOG = [
    {'schema_version': '1.0.0', 'date': '2026-10-16', 'changes': [
        'First release of the Commonworld static API v1 at /api/v1/ with the Atlas module at /api/v1/atlas/.',
        'Endpoints: index.json, atlas/index.json, atlas/platforms.json, atlas/platforms/{id}.json, atlas/categories/{category}.json, atlas/earn.json.',
        'OpenAPI 3.1 description (openapi.json) and JSON Schema 2020-12 schemas (schemas/).',
        'Same records as the older /atlas/*.json files, which keep working unchanged.',
        'An ID or category that does not exist returns HTTP 404 (the site\'s HTML error page, not JSON). Never construct an ID; take it from atlas/platforms.json.']},
]
VERSIONING = ('Semantic versioning of the data shape (schema_version). Minor and patch versions only add optional fields or files, '
              'so a v1 client keeps working. Any breaking change (a removed or renamed field, a changed type or meaning, a moved URL) '
              'ships as /api/v2/, and /api/v1/ keeps working.')


def schema_url(origin, name):
    return f'{origin}{API_BASE}/schemas/{name}'


# ---------------------------------------------------------------- schemas
def _nullable(t):
    return {'type': [t, 'null']} if isinstance(t, str) else t


def schemas(origin, categories):
    """{file name: JSON Schema 2020-12}. categories: list of category keys (enum)."""
    S = lambda n: schema_url(origin, n)
    utc = {'type': 'string', 'pattern': UTC_PATTERN, 'format': 'date-time'}
    utc_n = {'type': ['string', 'null'], 'pattern': UTC_PATTERN, 'format': 'date-time'}
    uri = {'type': 'string', 'format': 'uri', 'pattern': '^https?://'}
    uri_n = {'type': ['string', 'null'], 'format': 'uri'}
    scalar = {'type': ['number', 'string', 'null']}
    money_flow = {'type': 'object', 'description': 'A supported money-flow claim as shown on the card.',
                  'required': ['statement', 'value', 'unit', 'window', 'basis', 'observed_at', 'source_url'],
                  'properties': {'statement': {'type': 'string'}, 'value': scalar, 'unit': {'type': ['string', 'null']},
                                 'window': {'type': ['string', 'null']}, 'basis': {'enum': BASES}, 'observed_at': utc_n, 'source_url': uri_n}}
    key_number = {'type': ['object', 'null'], 'description': 'The headline figure shown on the card, or null.',
                  'required': ['kind', 'value', 'unit', 'window', 'basis', 'observed_at', 'source_url'],
                  'properties': {'kind': {'type': 'string'}, 'value': scalar, 'unit': {'type': ['string', 'null']}, 'window': {'type': ['string', 'null']},
                                 'basis': {'enum': BASES}, 'observed_at': utc_n, 'source_url': uri_n}}
    claim = {'type': 'object', 'description': 'One checked statement with its source, basis, outcome and observation time. Extra keys (history, recheck, methods) may appear.',
             'required': ['kind', 'statement', 'basis', 'outcome'],
             'properties': {'kind': {'type': 'string'}, 'statement': {'type': 'string'}, 'value': scalar, 'unit': {'type': ['string', 'null']},
                            'window': {'type': ['string', 'null']}, 'basis': {'enum': BASES}, 'outcome': {'enum': OUTCOMES},
                            'source_url': uri_n, 'quote': {'type': ['string', 'null']}, 'observed_at': utc_n,
                            'methods': {'type': 'array', 'items': {'type': 'string'}}, 'history': {'type': 'array', 'items': {'type': 'object'}},
                            'recheck': {'type': 'object'}}}
    summary_props = {
        'id': {'type': 'string', 'pattern': ID_PATTERN, 'description': 'Permanent ID (URL slug). Never construct one: take it from platforms.json.'},
        'name': {'type': 'string'}, 'url': uri, 'json_url': uri, 'website': uri_n,
        'category': {'enum': categories}, 'category_label': {'type': 'string'}, 'type': {'enum': ENTITY_TYPES + [None]},
        'status': {'enum': STATUSES}, 'summary': {'type': 'string'}, 'tags': {'type': 'array', 'items': {'type': 'string'}},
        'has_money_flow': {'type': 'boolean'}, 'money_flow': {'type': 'array', 'items': {'$ref': '#/$defs/moneyFlow'}},
        'key_number': {'$ref': '#/$defs/keyNumber'}, 'verified_at': utc_n, 'last_checked': utc_n,
        'claims_count': {'type': 'integer', 'minimum': 0}, 'disclosure': {'type': ['string', 'null']}}
    summary = {'type': 'object', 'description': 'Stable public fields of one published Atlas entry (as in platforms.json).',
               'required': list(summary_props), 'properties': summary_props}
    defs = {'platformSummary': summary, 'moneyFlow': money_flow, 'keyNumber': key_number, 'claim': claim}
    platform = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': S('platform.schema.json'),
                'title': 'Commonworld Atlas entry', 'description': 'One published Atlas entry with all its claims and sources (/api/v1/atlas/platforms/{id}.json).',
                'type': 'object', 'allOf': [{'$ref': '#/$defs/platformSummary'}],
                'required': ['schema_version', 'licence', 'source', 'generated_at', 'badge_status', 'badge_svg', 'badge_svg_dark', 'badge_page', 'claims'],
                'properties': {'schema_version': {'type': 'string'}, 'licence': {'type': 'string'}, 'source': uri, 'generated_at': utc_n,
                               'badge_status': {'type': 'string'}, 'badge_svg': uri, 'badge_svg_dark': uri, 'badge_page': uri,
                               'claims': {'type': 'array', 'items': {'$ref': '#/$defs/claim'}}, 'qa_status': {'type': ['string', 'null']}},
                '$defs': defs}
    list_meta = {'schema_version': {'type': 'string'}, 'name': {'type': 'string'}, 'description': {'type': 'string'}, 'url': uri,
                 'generated_at': utc_n, 'newest_observation': utc_n, 'licence': {'type': 'string'}, 'licence_url': uri, 'source': uri,
                 'corrections': uri, 'protocol': uri, 'full_data': uri, 'count': {'type': 'integer', 'minimum': 0}, 'fields_note': {'type': 'string'},
                 'platforms': {'type': 'array', 'items': {'$ref': 'platform.schema.json#/$defs/platformSummary'}}}
    plist = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': S('platform-list.schema.json'),
             'title': 'Commonworld Atlas entry list', 'description': 'All published entries (/api/v1/atlas/platforms.json).',
             'type': 'object', 'required': ['schema_version', 'name', 'url', 'generated_at', 'licence', 'count', 'platforms'], 'properties': list_meta}
    category = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': S('category.schema.json'),
                'title': 'Commonworld Atlas category', 'description': 'Published entries of one category (/api/v1/atlas/categories/{category}.json).',
                'type': 'object', 'required': ['schema_version', 'name', 'generated_at', 'licence', 'category', 'category_label', 'count', 'platforms'],
                'properties': list_meta | {'category': {'enum': categories}, 'category_label': {'type': 'string'}}}
    earn_row = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': S('earn-row.schema.json'),
                'title': 'Where agents get paid: one row', 'description': 'One live entry with a supported money figure, as shown on its card. Values are never converted between units.',
                'type': 'object', 'required': ['id', 'name', 'url', 'json_url', 'category', 'value', 'unit', 'window', 'basis', 'observed_at', 'source_url', 'unit_family', 'tier', 'note', 'group'],
                'properties': {'id': {'type': 'string', 'pattern': ID_PATTERN}, 'name': {'type': 'string'}, 'url': uri, 'json_url': uri,
                               'category': {'enum': categories}, 'value': scalar, 'unit': {'type': ['string', 'null']}, 'window': {'type': ['string', 'null']},
                               'basis': {'enum': BASES}, 'observed_at': utc_n, 'source_url': uri_n, 'unit_family': {'type': 'string'},
                               'tier': {'type': 'string'}, 'note': {'type': ['string', 'null']}, 'group': {'type': 'string'}}}
    earn = {'$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': S('earn.schema.json'),
            'title': 'Where agents get paid', 'description': 'Rows grouped by unit (/api/v1/atlas/earn.json).',
            'type': 'object', 'required': ['schema_version', 'name', 'url', 'generated_at', 'licence', 'count', 'no_figure', 'rows'],
            'properties': {'schema_version': {'type': 'string'}, 'name': {'type': 'string'}, 'url': uri, 'generated_at': utc_n, 'licence': {'type': 'string'},
                           'source': uri, 'fields_note': {'type': 'string'}, 'count': {'type': 'integer', 'minimum': 0},
                           'no_figure': {'type': 'array', 'items': {'type': 'string', 'pattern': ID_PATTERN}},
                           'rows': {'type': 'array', 'items': {'$ref': 'earn-row.schema.json'}}}}
    return {'platform.schema.json': platform, 'platform-list.schema.json': plist, 'category.schema.json': category,
            'earn-row.schema.json': earn_row, 'earn.schema.json': earn}


# ---------------------------------------------------------------- OpenAPI 3.1
def openapi(origin, categories, example_ids, docs_url, licence):
    js = lambda ref, desc: {'200': {'description': desc, 'content': {'application/json': {'schema': {'$ref': ref}}}}}
    obj = lambda desc: {'200': {'description': desc, 'content': {'application/json': {'schema': {'type': 'object'}}}}}
    idp = {'name': 'id', 'in': 'path', 'required': True,
           'description': 'Permanent entry ID (URL slug). Never construct or guess an ID; take it from atlas/platforms.json (or a category file). An ID not listed there does not exist.',
           'schema': {'type': 'string', 'pattern': ID_PATTERN}, 'examples': {x: {'value': x} for x in example_ids}}
    catp = {'name': 'category', 'in': 'path', 'required': True, 'description': 'Category key, as listed in atlas/index.json.',
            'schema': {'type': 'string', 'enum': categories}}
    return {
        'openapi': '3.1.0',
        'info': {'title': 'Commonworld API', 'version': SCHEMA_VERSION,
                 'summary': 'Static, read-only JSON API of Commonworld. First module: the Atlas of agent platforms.',
                 'description': ('Plain static JSON files, rebuilt with every change to the site. No key, no rate limit beyond fair use; '
                                 'CORS is open (Access-Control-Allow-Origin: *). Responses may be cached by Cloudflare and browsers for up to a few hours. '
                                 + VERSIONING + f' Human documentation: {docs_url}'),
                 'license': {'name': f'Data: {licence}', 'url': 'https://creativecommons.org/licenses/by/4.0/'}},
        'servers': [{'url': f'{origin}{API_BASE}', 'description': 'Commonworld (canonical)'}],
        'externalDocs': {'url': docs_url, 'description': 'Commonworld API documentation'},
        'tags': [{'name': 'api', 'description': 'API root'}, {'name': 'atlas', 'description': 'Atlas of agent platforms'}],
        'paths': {
            '/index.json': {'get': {'tags': ['api'], 'operationId': 'getApiIndex', 'summary': 'API root: version, modules and links', 'responses': obj('API root document')}},
            '/changelog.json': {'get': {'tags': ['api'], 'operationId': 'getChangelog', 'summary': 'Changelog of schema_version', 'responses': obj('Changelog')}},
            '/atlas/index.json': {'get': {'tags': ['atlas'], 'operationId': 'getAtlasIndex', 'summary': 'Atlas module: counts, categories and links', 'responses': obj('Atlas index')}},
            '/atlas/platforms.json': {'get': {'tags': ['atlas'], 'operationId': 'listPlatforms', 'summary': 'All published entries',
                                              'responses': js('./schemas/platform-list.schema.json', 'All published entries')}},
            '/atlas/platforms/{id}.json': {'get': {'tags': ['atlas'], 'operationId': 'getPlatform', 'summary': 'One entry with all claims and sources', 'parameters': [idp],
                                                   'responses': js('./schemas/platform.schema.json', 'One entry') | {'404': {'description': 'No entry with this ID'}}}},
            '/atlas/categories/{category}.json': {'get': {'tags': ['atlas'], 'operationId': 'listCategory', 'summary': 'Entries of one category', 'parameters': [catp],
                                                          'responses': js('./schemas/category.schema.json', 'Entries of one category') | {'404': {'description': 'No such category'}}}},
            '/atlas/earn.json': {'get': {'tags': ['atlas'], 'operationId': 'getEarn', 'summary': 'Where agents get paid: money figures grouped by unit',
                                         'responses': js('./schemas/earn.schema.json', 'Money figures by unit')}},
        },
    }


def expand_paths(spec, ids, categories):
    """Every concrete file path (under API_BASE) the OpenAPI spec promises."""
    out = []
    for p in spec['paths']:
        if '{id}' in p:
            out += [p.replace('{id}', i) for i in ids]
        elif '{category}' in p:
            out += [p.replace('{category}', k) for k in categories]
        else:
            out.append(p)
    return out


def changelog_md():
    lines = ['# Commonworld API changelog', '', VERSIONING, '']
    for r in CHANGELOG:
        lines += [f"## {r['schema_version']} ({r['date']})", ''] + [f'- {c}' for c in r['changes']] + ['']
    return '\n'.join(lines)


# ---------------------------------------------------------------- tiny JSON Schema validator (subset of 2020-12 used above)
_TYPES = {'object': dict, 'array': list, 'string': str, 'boolean': bool, 'null': type(None)}


def _is(v, t):
    if t == 'integer':
        return isinstance(v, int) and not isinstance(v, bool)
    if t == 'number':
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    return isinstance(v, _TYPES[t])


def _resolve(ref, base_name, registry):
    name, _, frag = ref.partition('#')
    name = name or base_name
    if name.startswith('./'):
        name = name[2:]
    doc = registry[name]
    node = doc
    for part in [x for x in frag.split('/') if x]:
        node = node[part]
    return node, name


def validate(inst, schema, registry, base_name, path='$', errs=None, limit=20):
    """Validate inst against schema; registry maps schema file name -> schema. Supports $ref (local and file#/$defs/x),
    allOf, type, enum, required, properties, items, pattern, minimum. Returns a list of 'path: message' strings."""
    errs = [] if errs is None else errs
    if len(errs) >= limit:
        return errs
    if '$ref' in schema:
        node, nb = _resolve(schema['$ref'], base_name, registry)
        validate(inst, node, registry, nb, path, errs, limit)
    for sub in schema.get('allOf', []):
        validate(inst, sub, registry, base_name, path, errs, limit)
    t = schema.get('type')
    if t is not None:
        ts = t if isinstance(t, list) else [t]
        if not any(_is(inst, x) for x in ts):
            errs.append(f'{path}: expected {"/".join(ts)}, got {type(inst).__name__}')
            return errs
    if 'enum' in schema and inst not in schema['enum']:
        errs.append(f'{path}: {inst!r} not in {schema["enum"]}')
    if isinstance(inst, str) and 'pattern' in schema and not re.search(schema['pattern'], inst):
        errs.append(f'{path}: {inst[:60]!r} does not match {schema["pattern"]}')
    if isinstance(inst, (int, float)) and not isinstance(inst, bool) and 'minimum' in schema and inst < schema['minimum']:
        errs.append(f'{path}: {inst} < {schema["minimum"]}')
    if isinstance(inst, dict):
        for k in schema.get('required', []):
            if k not in inst:
                errs.append(f'{path}: missing required {k!r}')
        for k, sub in (schema.get('properties') or {}).items():
            if k in inst:
                validate(inst[k], sub, registry, base_name, f'{path}.{k}', errs, limit)
    if isinstance(inst, list) and 'items' in schema:
        for i, v in enumerate(inst):
            validate(v, schema['items'], registry, base_name, f'{path}[{i}]', errs, limit)
    return errs
