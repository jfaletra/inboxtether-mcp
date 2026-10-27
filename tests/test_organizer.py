from organizer.model import Message,Policy,Rule,CATEGORIES
def mail(uid=1, sender='news@example.com', subject='Industry bulletin', body='Routine information.', flags=(), extra=''):
    raw = (f'From: {sender}\r\nTo: owner@example.com\r\nSubject: {subject}\r\n'
           f'Date: Mon, 19 Oct 2026 12:00:00 +0000\r\nMessage-ID: <synthetic-{uid}@example.com>\r\n'
           f'Authentication-Results: mx.example.com; dmarc=pass header.from=example.com; dkim=pass header.d=example.com\r\n{extra}MIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n').encode()
    return Message(uid, raw, flags)


def policy():
    return Policy('owner', 'synthetic-2',trusted_authserv_ids=('mx.example.com',),authentication_boundary_sha256='0'*64, customer_addresses=('customer@example.com',),
                  customer_domains=('customers.example.com',), protected_thread_ids=('<protected@example.com>',),
                  rules=tuple(Rule(str(i), 'news@example.com', category, category + ' bulletin')
                              for i, category in enumerate(CATEGORIES)))


