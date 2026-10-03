"""Document-local JSON Schema validation shared by runtime and evaluation."""

from copy import deepcopy
from urllib.parse import unquote


def validator(schema):
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry
        from referencing.exceptions import NoSuchResource
    except ImportError as exc:
        raise ValueError('Install JSON Schema support: python -m pip install jsonschema') from exc

    # Visit schema positions only: a literal in const/enum/examples can contain
    # any key, including $ref, without becoming a schema reference.
    maps = {'$defs', 'definitions', 'properties', 'patternProperties', 'dependentSchemas'}
    single = {'additionalProperties', 'unevaluatedProperties', 'propertyNames', 'items',
              'additionalItems', 'unevaluatedItems', 'contains', 'not', 'if', 'then', 'else'}
    arrays = {'allOf', 'anyOf', 'oneOf', 'prefixItems'}
    visited = set()

    def references(value, root=False):
        if isinstance(value, dict):
            if id(value) in visited:
                return
            visited.add(id(value))
            if not root and '$id' in value:
                raise ValueError('JSON schemas use one document; nested $id is unsupported')
            if '$schema' in value and value['$schema'] != 'https://json-schema.org/draft/2020-12/schema':
                raise ValueError('JSON schemas use JSON Schema Draft 2020-12')
            for key, child in value.items():
                if key in {'$ref', '$dynamicRef'}:
                    if not isinstance(child, str) or (child != '#' and not child.startswith('#/')):
                        raise ValueError('JSON schemas support document-local JSON Pointer references only')
                    target = schema
                    try:
                        for token in unquote(child[2:]).split('/') if child != '#' else []:
                            token = token.replace('~1', '/').replace('~0', '~')
                            target = target[int(token)] if isinstance(target, list) else target[token]
                    except (KeyError, IndexError, ValueError, TypeError) as exc:
                        raise ValueError('JSON schema has an unresolved local reference') from exc
                    try:
                        Draft202012Validator.check_schema(target)
                    except Exception as exc:
                        raise ValueError('JSON schema reference does not point to a schema') from exc
                    references(target, root=target is schema)
                elif key in maps and isinstance(child, dict):
                    for subschema in child.values():
                        references(subschema)
                elif key in single:
                    references(child)
                elif key in arrays and isinstance(child, list):
                    for subschema in child:
                        references(subschema)

    references(schema, root=True)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:
        raise ValueError('Invalid evaluation JSON Schema') from exc
    def no_remote(uri):
        raise NoSuchResource(ref=uri)

    return Draft202012Validator(schema, registry=Registry(retrieve=no_remote))


def inline_schema(schema):
    """Inline finite local references for embedding inside provider output schemas."""
    validator(schema)
    maps = {'properties', 'patternProperties', 'dependentSchemas'}
    single = {'additionalProperties', 'unevaluatedProperties', 'propertyNames', 'items',
              'additionalItems', 'unevaluatedItems', 'contains', 'not', 'if', 'then', 'else'}
    arrays = {'allOf', 'anyOf', 'oneOf', 'prefixItems'}

    def expand(value, ancestors=()):
        if not isinstance(value, dict):
            return deepcopy(value)
        if id(value) in ancestors:
            raise ValueError('Action parameters require a finite, nonrecursive schema')
        ancestors = (*ancestors, id(value))
        output = {}
        for key, child in value.items():
            if key in {'$ref', '$dynamicRef'}:
                target = schema
                for token in unquote(child[2:]).split('/') if child != '#' else []:
                    token = token.replace('~1', '/').replace('~0', '~')
                    target = target[int(token)] if isinstance(target, list) else target[token]
                output.setdefault('allOf', []).append(expand(target, ancestors))
            elif key in maps:
                output[key] = {k: expand(v, ancestors) for k, v in child.items()}
            elif key in single:
                output[key] = expand(child, ancestors)
            elif key in arrays:
                output.setdefault(key, []).extend(expand(v, ancestors) for v in child)
            elif key not in {'$defs', 'definitions', '$id', '$schema'}:
                output[key] = deepcopy(child)
        return output

    return expand(schema)
