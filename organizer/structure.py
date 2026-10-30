"""Small strict bounded IMAP response/BODYSTRUCTURE reader. No code evaluation."""
from .content import (ATTACHMENT_TYPES, ENCRYPTED, MAX_DEPTH, MAX_PART, MAX_PARTS,
                      SUPPORTED_ENCODINGS, ContentRefused, check)


def parse(data):
    check(isinstance(data, bytes) and len(data) <= 131072)
    position, tokens = 0, 0

    def value(depth=0):
        nonlocal position, tokens
        tokens += 1
        check(depth <= MAX_DEPTH + 10 and tokens <= 10000)
        while position < len(data) and data[position] == 32:
            position += 1
        check(position < len(data))
        current = data[position]
        if current == 40:
            position += 1
            result = []
            while True:
                while position < len(data) and data[position] == 32: position += 1
                check(position < len(data))
                if data[position] == 41:
                    position += 1
                    return result
                result.append(value(depth + 1))
        if current == 34:
            position += 1
            result = bytearray()
            while position < len(data):
                char = data[position]; position += 1
                if char == 34:
                    return result.decode('utf-8', errors='strict')
                if char == 92:
                    check(position < len(data) and data[position] in (34, 92))
                    char = data[position]; position += 1
                check(char >= 32 and char != 127)
                result.append(char)
            raise ContentRefused('Unterminated IMAP string.')
        start = position
        while position < len(data) and data[position] not in (32, 40, 41):
            check(data[position] >= 33 and data[position] < 127 and data[position] not in (34, 123, 125))
            position += 1
        check(position > start)
        atom = data[start:position].decode('ascii')
        if atom.upper() == 'NIL': return None
        if atom.isdigit():
            check(len(atom) <= 10)
            return int(atom)
        return atom
    result = []
    while position < len(data):
        if data[position:] == b' ': break
        result.append(value())
    return result


def metadata(data):
    parsed = parse(data)
    check(len(parsed) == 2 and type(parsed[0]) is int and isinstance(parsed[1], list))
    attrs = parsed[1]
    check(len(attrs) % 2 == 0)
    result = {}
    for index in range(0, len(attrs), 2):
        key = attrs[index]
        check(isinstance(key, str) and key.upper() not in result)
        result[key.upper()] = attrs[index + 1]
    return result


def parameters(values):
    if values is None: return {}
    check(isinstance(values, list) and len(values) % 2 == 0 and len(values) <= 100)
    result = {}
    for index in range(0, len(values), 2):
        key, val = values[index:index+2]
        check(isinstance(key, str) and isinstance(val, str) and key.upper() not in result and len(val) <= 4096)
        result[key.upper()] = val
    return result


def sections(tree):
    """Describe fetchable body text and attachment metadata without fetching payloads."""
    texts, attachments = [], []
    blocked, count = False, 0

    def walk(node, section='', depth=0):
        nonlocal count, blocked
        count += 1
        check(count <= MAX_PARTS and depth <= MAX_DEPTH and isinstance(node, list) and len(node) >= 2)
        if isinstance(node[0], list):
            index = 0
            while index < len(node) and isinstance(node[index], list): index += 1
            check(index < len(node) and isinstance(node[index], str))
            subtype = node[index].upper()
            disposition = node[index + 2] if len(node) > index + 2 else None
            if disposition is not None:
                check(isinstance(disposition, list) and len(disposition) == 2 and isinstance(disposition[0], str))
                names = parameters(disposition[1])
                if disposition[0].upper() == 'ATTACHMENT' or any(k.startswith('FILENAME') for k in names):
                    blocked = True
                    return
            if subtype not in ('MIXED', 'ALTERNATIVE', 'RELATED'):
                blocked = True
                return
            for child, value in enumerate(node[:index], 1):
                walk(value, (section + '.' if section else '') + str(child), depth + 1)
            return
        check(len(node) >= 7 and isinstance(node[0], str) and isinstance(node[1], str))
        kind = (node[0] + '/' + node[1]).lower()
        if kind in ENCRYPTED or node[0].upper() == 'MESSAGE':
            blocked = True
            return
        params = parameters(node[2])
        encoding, size = node[5], node[6]
        check(isinstance(encoding, str) and type(size) is int and 0 <= size <= 4294967295)
        text = node[0].upper() == 'TEXT'
        if text:
            check(len(node) >= 8 and type(node[7]) is int)
        extension = 8 if text else 7
        disposition = node[extension + 1] if len(node) > extension + 1 else None
        disp, disp_params = '', {}
        if disposition is not None:
            check(isinstance(disposition, list) and len(disposition) == 2 and isinstance(disposition[0], str))
            disp, disp_params = disposition[0].upper(), parameters(disposition[1])
        filename = disp_params.get('FILENAME', disp_params.get('FILENAME*', params.get('NAME', params.get('NAME*', ''))))
        extended = any(k.startswith('FILENAME*') or k.startswith('NAME*') for k in (*params, *disp_params))
        if extended:
            # Ambiguous RFC2231 continuations are metadata uncertainty, never a body-text fetch.
            blocked = True
            filename = filename or '(unsupported extended filename)'
        section = section or '1'
        if filename or disp == 'ATTACHMENT' or kind not in ('text/plain', 'text/html'):
            attachments.append({'filename': filename, 'content_type': kind, 'disposition': disp.lower(),
                                'size': size, 'section': section})
            if kind not in ATTACHMENT_TYPES: blocked = True
            return
        check(size <= MAX_PART and encoding.upper() in SUPPORTED_ENCODINGS)
        charset = params.get('CHARSET', 'us-ascii')
        check(len(charset) <= 100)
        texts.append({'section': section, 'content_type': kind, 'charset': charset,
                      'encoding': encoding.upper(), 'size': size})
    walk(tree)
    return texts, attachments, blocked
