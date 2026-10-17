"""Exercise real smtplib DATA framing on socketpairs; no network SMTP listener."""
import socket
import smtplib
import threading
import unittest
from unittest.mock import patch


class SMTPWireTests(unittest.TestCase):
    def test_exact_mime_after_dot_transparency(self):
        client, peer = socket.socketpair()
        raw = b'From: sender@example.com\r\nTo: to@example.com\r\nSubject: Synthetic\r\n\r\n.one\r\n..two\r\nbody\r\n'
        received, errors = [], []
        def fake_relay():
            try:
                with peer, peer.makefile('rwb', buffering=0) as stream:
                    self.assertEqual(stream.readline(), b'data\r\n')
                    stream.write(b'354 synthetic\r\n')
                    while True:
                        line = stream.readline()
                        if line == b'.\r\n':
                            break
                        self.assertTrue(line)
                        received.append(line[1:] if line.startswith(b'..') else line)
                    stream.write(b'250 synthetic accepted\r\n')
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=fake_relay, daemon=True); worker.start()
        smtp = smtplib.SMTP()
        smtp.sock = client
        try:
            self.assertEqual(smtp.data(raw)[0], 250)
            self.assertEqual(b''.join(received), raw)
        finally:
            smtp.close(); worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors)

    def test_smtp_data_rejection_before_bytes(self):
        client, peer = socket.socketpair()
        def fake_relay():
            with peer, peer.makefile('rwb', buffering=0) as stream:
                stream.readline(); stream.write(b'554 synthetic rejection\r\n')
        worker = threading.Thread(target=fake_relay, daemon=True); worker.start()
        smtp = smtplib.SMTP(); smtp.sock = client
        try:
            with self.assertRaises(smtplib.SMTPDataError): smtp.data(b'synthetic\r\n')
        finally:
            smtp.close(); worker.join(timeout=5)
        self.assertFalse(worker.is_alive())
