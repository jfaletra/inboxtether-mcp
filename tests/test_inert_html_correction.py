"""Synthetic structures from reviewed blockers; no production messages or identities."""
import copy,dataclasses,json,unittest
from pathlib import Path
from unittest.mock import patch
from email.message import EmailMessage
from email import policy as ep
from organizer.content import ReadableHTML,analyze,from_raw,ContentRefused,MimeView,TextSection,decode_text
from organizer.classifier import ClientPolicy,ContextualSender
from organizer.model import Message
from test_organizer import policy,mail
from test_organizer_formats import formatted
from test_automatic_filing import AutomaticTests

class InertHTMLTests(unittest.TestCase):
 def setUp(self):
  self.rows=json.loads(Path(__file__).with_name('false_keep_shapes.json').read_text())
  self.p=ClientPolicy(policy(),(ContextualSender('news@example.com','supplier'),),mode='practical')
 def accept(self,m,category='Marketing',risk='clear',reason='promotion'):
  return self.p.accept(m,{'category':category,'customer_risk':risk,'reason':reason},'a'*64,'b'*64)
 def test_three_real_shaped_promotions_reach_client(self):
  for row in self.rows[:3]:
   with self.subTest(shape=row['id']):
    m=formatted(html=row['html']);e=copy.deepcopy(m.evidence())
    with patch('socket.socket.connect',side_effect=AssertionError('No network')):
     guard,packet=self.p.prepare(m);self.assertIsNotNone(packet);decision=self.accept(m)
    self.assertEqual(decision['category'],'Marketing');self.assertTrue(decision['move_eligible']);self.assertEqual(m.evidence(),e)
 def test_closing_br_preserves_visible_and_protection_tokens(self):
  a=ReadableHTML().result('<div>First<br>Second</br>Third</div>')
  b=ReadableHTML().result('<div>First<br>SecondThird</div>')
  self.assertEqual(a,b);self.assertFalse(a[2])
 def test_stray_body_never_hides_remaining_customer_text(self):
  html='<html><p>Newsletter</p></body><p>I need a refund.</p></html>'
  self.assertIn('I need a refund',ReadableHTML().result(html)[1]);self.assertIsNone(self.p.prepare(formatted(html=html))[1])
 def test_stray_body_does_not_unwind_open_elements(self):
  self.assertTrue(ReadableHTML().result('<html><div>Offers</body></html>')[2])
 def test_existing_open_body_behavior_unchanged(self):
  text,alltext,bad=ReadableHTML().result('<html><body><p>All evidence</p></body></html>');self.assertFalse(bad);self.assertIn('All evidence',alltext)
 def test_only_exact_compact_doctype_form_tolerated(self):
  for doc in ('<!doctypehtml>','<!DOCTYPEHTML>','<!DOCTYPE html>'):
   self.assertFalse(ReadableHTML().result(doc+'<p>Bulletin</p>')[2])
  for doc in ('<!DOCTYPE html SYSTEM "file:///secret">','<!DOCTYPE html [<!ENTITY x "hidden">]>','<!doctypehtml SYSTEM "https://external.example.org/x">','<?xml version="1.0"?>'):
   with self.subTest(declaration=doc):self.assertIsNone(self.p.prepare(formatted(html=doc+'<p>Offers</p>'))[1])
 def test_other_unmatched_closers_still_rejected(self):
  for tag in ('img','hr','input','script','iframe','table','div','span','form'):
   with self.subTest(tag=tag):self.assertTrue(ReadableHTML().result('<p>Offers</p></'+tag+'>')[2])
 def test_active_content_still_rejected_with_each_tolerance(self):
  for row in self.rows[:3]:
   for evil in ('<script>run()</script>','<iframe src="https://external.example.org/x"></iframe>','<img src="x" onerror="run()">','<a href="javascript:run()">Offer</a>','<svg><script>run()</script></svg>','<meta http-equiv="refresh" content="0;url=https://external.example.org">','<form><input></form>','<img src="data:image/png;base64,AAAA">'):
    with self.subTest(shape=row['id'],evil=evil):self.assertIsNone(self.p.prepare(formatted(html=row['html']+evil))[1])
 def test_incomplete_markup_and_nesting_still_rejected(self):
  for html in ('<html><div>Offers','<div><span>Offer</div>','<p><!-- never closed','<p>Offer<unclosed','<unknown>Offer</unknown>'):
   with self.subTest(html=html):self.assertIsNone(self.p.prepare(formatted(html=html))[1])
 def test_customer_intent_protected_with_every_fixed_shape(self):
  for row in self.rows[:3]:
   for customer in ('I need a refund.','Can you help with my order?','My firearm transfer is arriving.','A customer asks about pickup.','Please advise on an FFL transfer.'):
    with self.subTest(shape=row['id'],customer=customer):
     m=formatted(html=row['html']+'<p>'+customer+'</p>');self.assertIsNone(self.p.prepare(m)[1]);self.assertFalse(self.accept(m)['move_eligible'])
 def test_unfinished_tail_cannot_hide_customer_evidence(self):
  for tail in ('<unclosed', '<unclosed I need a refund', '</body><unfinished My order question'):
   self.assertIsNone(self.p.prepare(formatted(html='<p>Routine offers</p>'+tail))[1])
 def test_known_customer_and_mixed_threads_protected(self):
  for row in self.rows[:3]:
   self.assertIsNone(self.p.prepare(formatted(html=row['html'],customer=True))[1])
   for header in ('References: <prior@example.com>\r\n','In-Reply-To: <prior@example.com>\r\n'):
    raw=formatted(html=row['html']).raw.replace(b'\r\n\r\n',b'\r\n'+header.encode()+b'\r\n',1);self.assertIsNone(self.p.prepare(Message(1,raw))[1])
 def test_alternative_hidden_and_attribute_customer_evidence_preserved(self):
  for html in ('<p style="display:none">I need a refund.</p>','<img alt="My order question" src="https://external.example.org/image">','<div>Can you help with my order?</div>'):
   m=formatted(plain='Routine offers.',html='<!doctypehtml><p>Sale</p></body>'+html);self.assertIsNone(self.p.prepare(m)[1])
 def test_customer_gunsmith_keyword_retained_for_ambiguous_inquiries(self):
  p=ClientPolicy(dataclasses.replace(policy(),customer_terms=('gunsmith',)),(),mode='practical')
  for subject,body in [('Gunsmith tools','Availability and prices for the attached list, please.'),('Question','Gunsmith tools: suitable for the attached project?')]:
   m=mail(sender='unknown@sender.example.org',subject=subject,body=body);self.assertEqual(p.prepare(m)[0]['reason'],'customer-protected');self.assertIsNone(p.prepare(m)[1])
 def test_customer_ffl_transfer_keyword_retained_for_ambiguous_inquiries(self):
  for subject,body in [('FFL transfer','Arriving Friday. Details attached.'),('FFL transfer webinar','Please send details for the attached situation.')]:
   m=mail(sender='unknown@sender.example.org',subject=subject,body=body);self.assertEqual(self.p.prepare(m)[0]['reason'],'customer-protected');self.assertIsNone(self.p.prepare(m)[1])
 def test_promotional_customer_word_false_positives_are_explicitly_not_silently_changed(self):
  p=ClientPolicy(dataclasses.replace(policy(),customer_terms=('gunsmith',)),(),mode='practical')
  self.assertEqual(p.prepare(formatted(html=self.rows[3]['html']))[0]['reason'],'customer-protected')
  self.assertEqual(self.p.prepare(formatted(html=self.rows[4]['html']))[0]['reason'],'customer-protected')
 def test_malformed_transfer_encoding_and_encrypted_content_remain_closed(self):
  for raw in (b'From: news@example.com\r\nContent-Type: text/html; charset=utf-8\r\nContent-Transfer-Encoding: base64\r\n\r\n!!!!',b'From: news@example.com\r\nContent-Type: multipart/encrypted; boundary=x\r\n\r\n--x\r\nContent-Type: application/pgp-encrypted\r\n\r\nopaque\r\n--x--'):
   self.assertIsNone(self.p.prepare(Message(1,raw))[1])
 def test_decode_failure_not_made_readable(self):
  with self.assertRaises(UnicodeError):decode_text(TextSection('1','text/html','utf-8','8BIT',b'\xff'))
 def test_client_uncertainty_remains_keep(self):
  for row in self.rows[:3]:self.assertFalse(self.accept(formatted(html=row['html']),risk='possible',reason='uncertain')['move_eligible'])
 def test_action_required_review_is_not_auto_marketing(self):
  m=formatted(html='<!doctypehtml><p>Please update your dealer license record in the owner portal.</p>');d=self.accept(m,'Review','clear','owner-review');self.assertEqual(d['category'],'Review');self.assertTrue(d['requires_owner_approval'])

class AutoRestrictionsTests(AutomaticTests):
 def test_review_stays_out_of_automatic_selection_with_corrected_parser(self):
  value=self.r.read();before=copy.deepcopy(value)
  for d in value['workflow']['decisions'].values():d['category']='Review'
  self.r.journal.write(value)
  from organization_errors import OrganizationError
  with self.assertRaises(OrganizationError):self.call('candidates',{'select_count':200,'filing_mode':'automatic'})
  self.assertEqual(self.box.moves,[]);self.assertEqual(self.r.read()['workflow']['decisions'],value['workflow']['decisions'])
