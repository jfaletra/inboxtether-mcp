"""Portable canonical-AST pins for the unchanged public v1.2.1 Reader/Draft code."""
import ast
import hashlib
import json


def contract_hash(node):
    def canonical(value):
        if isinstance(value, ast.AST):
            fields={name:canonical(child) for name,child in ast.iter_fields(value)
                    if not (name=='type_params' and child==[])}
            return {'node':type(value).__name__,'fields':fields}
        if isinstance(value,list):return [canonical(child) for child in value]
        if isinstance(value,bytes):return {'bytes':value.hex()}
        return value
    # Do not depend on ast.dump's version-specific formatting or field order.
    encoded=json.dumps(canonical(node),sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()
