# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from freezegun import freeze_time
from markupsafe import Markup
from requests import Session, PreparedRequest, Response

import datetime
import werkzeug

from odoo import tools
from odoo.addons.mass_mailing.tests.common import MassMailCommon
from odoo.tests import HttpCase, tagged
from odoo.tools import mute_logger


class TestMailingControllersCommon(MassMailCommon, HttpCase):

    @classmethod
    def setUpClass(cls):
        super(TestMailingControllersCommon, cls).setUpClass()

        # cleanup lists
        cls.env['mailing.list'].search([]).unlink()

        cls._create_mailing_list()
        cls.test_mailing_on_contacts = cls.env['mailing.mailing'].create({
            'body_html': '<p>Hello <t t-out="object.name"/><br />Go to <a id="url" href="https://www.example.com/foo/bar?baz=qux">this link</a></p>',
            'mailing_domain': [],
            'mailing_model_id': cls.env['ir.model']._get_id('mailing.contact'),
            'mailing_type': 'mail',
            'name': 'TestMailing on Contacts',
            'subject': 'TestMailing on Contacts',
        })
        cls.test_mailing_on_documents = cls.env['mailing.mailing'].create({
            'body_html': '<p>Hello <t t-out="object.name"/><br />Go to <a id="url" href="https://www.example.com/foo/bar?baz=qux">this link</a></p>',
            'mailing_domain': [],
            'mailing_model_id': cls.env['ir.model']._get_id('res.partner'),
            'mailing_type': 'mail',
            'name': 'TestMailing on Documents',
            'subject': 'TestMailing on Documents',
        })
        cls.test_mailing_on_lists = cls.env['mailing.mailing'].create({
            'body_html': '<p>Hello <t t-out="object.name"/><br />Go to <a id="url" href="https://www.example.com/foo/bar?baz=qux">this link</a></p>',
            'contact_list_ids': [(4, cls.mailing_list_1.id), (4, cls.mailing_list_2.id)],
            'mailing_model_id': cls.env['ir.model']._get_id('mailing.list'),
            'mailing_type': 'mail',
            'name': 'TestMailing on Lists',
            'reply_to': cls.email_reply_to,
            'subject': 'TestMailing on Lists',
        })

        cls.test_contact = cls.mailing_list_1.contact_ids[0]

        # freeze time base value
        cls._reference_now = datetime.datetime(2022, 6, 14, 10, 0, 0)

    @classmethod
    def _request_handler(cls, s: Session, r: PreparedRequest, /, **kw):
        if r.url.startswith('https://www.example.com/foo/bar'):
            r = Response()
            r.status_code = 200
            return r
        return super()._request_handler(s, r, **kw)


@tagged('mailing_portal', 'post_install', '-at_install')
class TestMailingControllers(TestMailingControllersCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.test_email = tools.formataddr(('Déboulonneur', '<fleurus@example.com>'))
        cls.test_email_normalized = 'fleurus@example.com'

    def test_assert_initial_values(self):
        """ Ensure test base data to ease test understanding. Globally test_email
        is member of 2 mailing public lists. """
        memberships = self.env['mailing.contact.subscription'].search([
            ('contact_id.email_normalized', '=', self.test_email_normalized)]
        )
        self.assertEqual(memberships.list_id, self.mailing_list_1 + self.mailing_list_3)
        self.assertEqual(memberships.mapped('opt_out'), [False, True])

        contact_l1 = self.mailing_list_1.contact_ids.filtered(
            lambda contact: contact.email == self.test_email_normalized
        )
        self.assertTrue(contact_l1)
        self.assertFalse(contact_l1.is_blacklisted)
        self.assertFalse(contact_l1.message_ids)
        subscription_l1 = self.mailing_list_1.subscription_ids.filtered(
            lambda subscription: subscription.contact_id == contact_l1
        )
        self.assertTrue(subscription_l1)
        self.assertFalse(subscription_l1.is_blacklisted)
        self.assertFalse(subscription_l1.opt_out)
        self.assertFalse(subscription_l1.unsubscription_date)

        contact_l2 = self.mailing_list_2.contact_ids.filtered(
            lambda contact: contact.email == self.test_email_normalized
        )
        self.assertFalse(contact_l2)

        contact_l3 = self.mailing_list_3.contact_ids.filtered(
            lambda contact: contact.email == self.test_email_normalized
        )
        self.assertTrue(contact_l3)
        self.assertTrue(contact_l3 != contact_l1)
        self.assertFalse(contact_l3.is_blacklisted)
        subscription_l3 = self.mailing_list_3.subscription_ids.filtered(
            lambda subscription: subscription.contact_id == contact_l3
        )
        self.assertFalse(subscription_l3.is_blacklisted)
        self.assertTrue(subscription_l3.opt_out)

        contact_l4 = self.mailing_list_4.contact_ids.filtered(
            lambda contact: contact.email == self.test_email_normalized
        )
        self.assertFalse(contact_l4)

        self.assertFalse(self.env['mail.blacklist'].search([('email', '=', self.test_email_normalized)]))

    @mute_logger('odoo.http', 'odoo.addons.website.models.ir_ui_view')
    def test_mailing_report_unsubscribe(self):
        """ Test deactivation of mailing report sending. It requires usage of
        a hash token. """
        test_mailing = self.test_mailing_on_lists.with_env(self.env)
        self.env['ir.config_parameter'].sudo().set_param(
            'mass_mailing.mass_mailing_reports', True
        )
        hash_token = test_mailing._generate_mailing_report_token(self.user_marketing.id)
        self.authenticate('user_marketing', 'user_marketing')

        # TEST: various invalid cases
        for test_user_id, test_token in [
            (self.user_marketing.id, ''),  # no token
            (self.user_marketing.id, 'zboobs'),  # invalid token
            (self.env.uid, hash_token),  # invalid credentials
        ]:
            with self.subTest(test_user_id=test_user_id, test_token=test_token):
                res = self.url_open(
                    werkzeug.urls.url_join(
                        test_mailing.get_base_url(),
                        f'mailing/report/unsubscribe?user_id={test_user_id}&token={test_token}',
                    )
                )
                self.assertEqual(res.status_code, 404)
                self.assertTrue(self.env['ir.config_parameter'].sudo().get_param('mass_mailing.mass_mailing_reports'))

        # TEST: not mailing user
        self.user_marketing.write({
            'groups_id': [(3, self.env.ref('mass_mailing.group_mass_mailing_user').id)],
        })
        res = self.url_open(
            werkzeug.urls.url_join(
                test_mailing.get_base_url(),
                f'mailing/report/unsubscribe?user_id={self.user_marketing.id}&token={hash_token}',
            )
        )
        self.assertEqual(res.status_code, 404)
        self.assertTrue(self.env['ir.config_parameter'].sudo().get_param('mass_mailing.mass_mailing_reports'))

        # TEST: finally valid call
        self.user_marketing.write({
            'groups_id': [(4, self.env.ref('mass_mailing.group_mass_mailing_user').id)],
        })
        res = self.url_open(
            werkzeug.urls.url_join(
                test_mailing.get_base_url(),
                f'mailing/report/unsubscribe?user_id={self.user_marketing.id}&token={hash_token}',
            )
        )
        self.assertEqual(res.status_code, 200)
        self.assertFalse(self.env['ir.config_parameter'].sudo().get_param('mass_mailing.mass_mailing_reports'))

    def test_mailing_unsubscribe_from_document_tour(self):
        """ Test portal unsubscribe on mailings performed on documents (not
        mailing lists or contacts). Primary effect is to automatically exclude
        the email (see tour).

        Two tests are performed (with and without existing list subscriptions)
        as it triggers the display of the mailing list part of the UI.

        Tour effects
          * unsubscribe from mailing based on a document = blocklist;
          * remove email from exclusion list;
          * re-add email to exclusion list;
        """
        test_mailing = self.test_mailing_on_documents.with_env(self.env)
        for test_email, tour_name in [
            ('"Not Déboulonneur" <not.fleurus@example.com>', 'mailing_portal_unsubscribe_from_document'),
            (self.test_email, 'mailing_portal_unsubscribe_from_document_with_lists'),
        ]:
            with self.subTest(test_email=test_email, tour_name=tour_name):
                test_partner = self.env['res.partner'].create({
                    'email': test_email,
                    'name': 'Test Déboulonneur'
                })
                self.assertFalse(test_partner.is_blacklisted)
                previous_messages = test_partner.message_ids

                # launch unsubscription tour
                hash_token = test_mailing._generate_mailing_recipient_token(test_partner.id, test_partner.email_normalized)
                with freeze_time(self._reference_now):
                    self.start_tour(
                        f"/mailing/{test_mailing.id}/unsubscribe?email={test_partner.email_normalized}&res_id={test_partner.id}&token={hash_token}",
                        tour_name,
                        login=None,
                    )

                # status update check
                self.assertTrue(test_partner.is_blacklisted)

                # partner (document): no messages added
                self.assertEqual(test_partner.message_ids, previous_messages)
                # posted messages on exclusion list record: activated, deactivated, activated again
                bl_record = self.env['mail.blacklist'].search([('email', '=', test_partner.email_normalized)])
                self.assertEqual(len(bl_record.message_ids), 4)
                msg_bl2, msg_unbl, msg_bl, msg_create = bl_record.message_ids
                self.assertEqual(
                    msg_bl2.body,
                    Markup(f'<p>Blocklist request from portal of mailing <a href="#" data-oe-model="{test_mailing._name}" data-oe-id="{test_mailing.id}">{test_mailing.subject}</a> (document <a href="#" data-oe-model="{test_partner._name}" data-oe-id="{test_partner.id}">Contact</a>)</p>')
                )
                self.assertEqual(
                    msg_unbl.body,
                    Markup(f'<p>Blocklist removal request from portal of mailing <a href="#" data-oe-model="{test_mailing._name}" data-oe-id="{test_mailing.id}">{test_mailing.subject}</a> (document <a href="#" data-oe-model="{test_partner._name}" data-oe-id="{test_partner.id}">Contact</a>)</p>')
                )
                self.assertEqual(
                    msg_bl.body,
                    Markup(f'<p>Blocklist request from unsubscribe link of mailing <a href="#" data-oe-model="{test_mailing._name}" data-oe-id="{test_mailing.id}">{test_mailing.subject}</a> (document <a href="#" data-oe-model="{test_partner._name}" data-oe-id="{test_partner.id}">Contact</a>)</p>')
                )
                self.assertEqual(msg_create.body, Markup('<p>Mail Blacklist created</p>'))

    def test_mailing_unsubscribe_from_list_tour(self):
        """ Test portal unsubscribe on mailings performed on mailing lists. Their
        effect is to opt-out from the mailing list.

        Tour effects
          * unsubscribe from mailing based on lists = opt-out from lists;
          * add feedback (opt-out) 'My feedback';'
          * add email to exclusion list;
        """
        test_mailing = self.test_mailing_on_lists.with_env(self.env)
        test_feedback = "My feedback"

        # fetch contact and its subscription and blacklist status, to see the tour effects
        contact_l1 = self.mailing_list_1.contact_ids.filtered(
            lambda contact: contact.email == self.test_email_normalized
        )
        subscription_l1 = self.mailing_list_1.subscription_ids.filtered(
            lambda subscription: subscription.contact_id == contact_l1
        )

        # launch unsubscribe tour
        hash_token = test_mailing._generate_mailing_recipient_token(contact_l1.id, contact_l1.email)
        with freeze_time(self._reference_now):
            self.start_tour(
                f"/mailing/{test_mailing.id}/unsubscribe?email={self.test_email_normalized}&res_id={contact_l1.id}&token={hash_token}",
                "mailing_portal_unsubscribe_from_list",
                login=None,
            )

        # status update check on list 1
        self.assertTrue(subscription_l1.opt_out)
        self.assertEqual(subscription_l1.unsubscription_date, self._reference_now)
        # status update check on list 2: unmodified (was not member, still not member)
        contact_l2 = self.mailing_list_2.contact_ids.filtered(
            lambda contact: contact.email == self.test_email_normalized
        )
        self.assertFalse(contact_l2)

        # posted messages on contact record for mailing list 1: feedback, unsubscription
        message_feedback = contact_l1.message_ids[0]
        self.assertEqual(
            message_feedback.body,
            Markup(f'<p>Feedback from {self.test_email_normalized}: {test_feedback}</p>')
        )
        message_unsub = contact_l1.message_ids[1]
        self.assertEqual(
            message_unsub.body,
            Markup(f'<p>The recipient <strong>unsubscribed from {self.mailing_list_1.name}</strong> mailing list(s)</p>')
        )

        # posted messages on exclusion list record: activated, deactivated, activated again
        bl_record = self.env['mail.blacklist'].search([('email', '=', contact_l1.email_normalized)])
        self.assertEqual(len(bl_record.message_ids), 2)
        msg_bl, msg_create = bl_record.message_ids
        self.assertEqual(
            msg_bl.body,
            Markup(f'<p>Blocklist request from portal of mailing <a href="#" data-oe-model="{test_mailing._name}" data-oe-id="{test_mailing.id}">{test_mailing.subject}</a> (document <a href="#" data-oe-model="{contact_l1._name}" data-oe-id="{contact_l1.id}">Mailing Contact</a>)</p>')
        )
        self.assertEqual(msg_create.body, Markup('<p>Mail Blacklist created</p>'))

    def test_mailing_unsubscribe_from_list_with_update_tour(self):
        """ Test portal unsubscribe on mailings performed on mailing lists. Their
        effect is to opt-out from the mailing list. Optional exclusion list can
        be done through interface (see tour).

        Tour effects
          * unsubscribe from mailing based on lists = opt-out from lists;
          * add feedback (opt-out) 'My feedback';'
          * add email to exclusion list;
          * remove email from exclusion list;
          * come back to List3;
          * re-add email to exclusion list;
        """
        test_mailing = self.test_mailing_on_lists.with_env(self.env)
        test_feedback = "My feedback"

        # fetch contact and its subscription and blacklist status, to see the tour effects
        contact_l1 = self.mailing_list_1.contact_ids.filtered(
            lambda contact: contact.email == self.test_email_normalized
        )
        subscription_l1 = self.mailing_list_1.subscription_ids.filtered(
            lambda subscription: subscription.contact_id == contact_l1
        )
        contact_l3 = self.mailing_list_3.contact_ids.filtered(
            lambda contact: contact.email == self.test_email_normalized
        )
        subscription_l3 = self.mailing_list_3.subscription_ids.filtered(
            lambda subscription: subscription.contact_id == contact_l3
        )

        # launch unsubscription tour
        hash_token = test_mailing._generate_mailing_recipient_token(contact_l1.id, contact_l1.email)
        with freeze_time(self._reference_now):
            self.start_tour(
                f"/mailing/{test_mailing.id}/unsubscribe?email={contact_l1.email}&res_id={contact_l1.id}&token={hash_token}",
                "mailing_portal_unsubscribe_from_list_with_update",
                login=None,
            )

        # status update check on list 1
        self.assertTrue(subscription_l1.opt_out)
        self.assertEqual(subscription_l1.unsubscription_date, self._reference_now)
        # status update check on list 3 (opt-in during test)
        self.assertFalse(subscription_l3.opt_out)
        self.assertFalse(subscription_l3.unsubscription_date)

        # posted messages on contact record for mailing list 1: feedback, unsubscription
        message_feedback = contact_l1.message_ids[0]
        self.assertEqual(
            message_feedback.body,
            Markup(f'<p>Feedback from {self.test_email_normalized}: {test_feedback}</p>')
        )
        message_unsub = contact_l1.message_ids[1]
        self.assertEqual(
            message_unsub.body,
            Markup(f'<p>The recipient <strong>unsubscribed from {self.mailing_list_1.name}</strong> mailing list(s)</p>')
        )

        # posted messages on contact record for mailing list 3: subscription
        message_unsub = contact_l3.message_ids[0]
        self.assertEqual(
            message_unsub.body,
            Markup(f'<p>The recipient <strong>subscribed to {self.mailing_list_3.name}</strong> mailing list(s)</p>')
        )

        # posted messages on exclusion list record: activated, deactivated, activated again
        bl_record = self.env['mail.blacklist'].search([('email', '=', contact_l1.email_normalized)])
        self.assertEqual(len(bl_record.message_ids), 4)
        msg_bl2, msg_unbl, msg_bl, msg_create = bl_record.message_ids
        self.assertEqual(
            msg_bl2.body,
            Markup(f'<p>Blocklist request from portal of mailing <a href="#" data-oe-model="{test_mailing._name}" data-oe-id="{test_mailing.id}">{test_mailing.subject}</a> (document <a href="#" data-oe-model="{contact_l1._name}" data-oe-id="{contact_l1.id}">Mailing Contact</a>)</p>')
        )
        self.assertEqual(
            msg_unbl.body,
            Markup(f'<p>Blocklist removal request from portal of mailing <a href="#" data-oe-model="{test_mailing._name}" data-oe-id="{test_mailing.id}">{test_mailing.subject}</a> (document <a href="#" data-oe-model="{contact_l1._name}" data-oe-id="{contact_l1.id}">Mailing Contact</a>)</p>')
        )
        self.assertEqual(
            msg_bl.body,
            Markup(f'<p>Blocklist request from portal of mailing <a href="#" data-oe-model="{test_mailing._name}" data-oe-id="{test_mailing.id}">{test_mailing.subject}</a> (document <a href="#" data-oe-model="{contact_l1._name}" data-oe-id="{contact_l1.id}">Mailing Contact</a>)</p>')
        )
        self.assertEqual(msg_create.body, Markup('<p>Mail Blacklist created</p>'))

    @mute_logger('odoo.http', 'odoo.addons.website.models.ir_ui_view')
    def test_mailing_view(self):
        """ Test preview of mailing. It requires either a token, either being
        mailing user. """
        test_mailing = self.test_mailing_on_documents.with_env(self.env)
        res_id, email_normalized = self.user_marketing.partner_id.id, self.user_marketing.email_normalized
        hash_token = test_mailing._generate_mailing_recipient_token(res_id, email_normalized)
        self.user_marketing.write({
            'groups_id': [(3, self.env.ref('mass_mailing.group_mass_mailing_user').id)],
        })
        self.authenticate('user_marketing', 'user_marketing')

        # TEST: various invalid cases
        for test_res_id, test_email, test_token in [
            (res_id, email_normalized, ''),  # no token
            (res_id, email_normalized, 'zboobs'),  # wrong token
            (self.env.user.partner_id.id, email_normalized, hash_token),  # mismatch
            (res_id, 'not.email@example.com', hash_token),  # mismatch
        ]:
            with self.subTest(test_email=test_email, test_res_id=test_res_id, test_token=test_token):
                res = self.url_open(
                    werkzeug.urls.url_join(
                        test_mailing.get_base_url(),
                        f'mailing/{test_mailing.id}/view?email={test_email}&res_id={test_res_id}&token={test_token}',
                    )
                )
                self.assertEqual(res.status_code, 403)

        # TEST: valid call using credentials
        res = self.url_open(
            werkzeug.urls.url_join(
                test_mailing.get_base_url(),
                f'mailing/{test_mailing.id}/view?email={email_normalized}&res_id={res_id}&token={hash_token}',
            )
        )
        self.assertEqual(res.status_code, 200)

        # TEST: invalid credentials but mailing user
        self.user_marketing.write({
            'groups_id': [(4, self.env.ref('mass_mailing.group_mass_mailing_user').id)],
        })
        res = self.url_open(
            werkzeug.urls.url_join(
                test_mailing.get_base_url(),
                f'mailing/{test_mailing.id}/view',
            )
        )
        self.assertEqual(res.status_code, 200)


@tagged('link_tracker', 'mailing_portal')
class TestMailingTracking(TestMailingControllersCommon):

    @mute_logger('odoo.addons.mail.models.mail_mail', 'odoo.addons.mass_mailing.models.mailing')
    def test_tracking_short_code(self):
        """ Test opening short code linked to a mailing trace: should set the
        trace as opened and clicked, create a click record. """
        mailing = self.test_mailing_on_lists.with_env(self.env)
        with self.mock_mail_gateway(mail_unlink_sent=False):
            mailing.action_send_mail()

        mail = self._find_mail_mail_wrecord(self.test_contact)
        mailing_trace = mail.mailing_trace_ids
        link_tracker_code = self._get_code_from_short_url(
            self._get_href_from_anchor_id(mail.body, 'url')
        )
        self.assertEqual(len(link_tracker_code), 1)
        self.assertEqual(link_tracker_code.link_id.count, 0)
        self.assertEqual(mail.state, 'sent')
        self.assertEqual(len(mailing_trace), 1)
        self.assertFalse(mailing_trace.links_click_datetime)
        self.assertFalse(mailing_trace.open_datetime)
        self.assertEqual(mailing_trace.trace_status, 'sent')

        short_link_url = werkzeug.urls.url_join(
            mail.get_base_url(),
            f'r/{link_tracker_code.code}/m/{mailing_trace.id}'
        )
        with freeze_time(self._reference_now):
            _response = self.url_open(short_link_url)

        self.assertEqual(link_tracker_code.link_id.count, 1)
        self.assertEqual(mailing_trace.links_click_datetime, self._reference_now)
        self.assertEqual(mailing_trace.open_datetime, self._reference_now)
        self.assertEqual(mailing_trace.trace_status, 'open')

    @mute_logger('odoo.addons.mail.models.mail_mail', 'odoo.addons.mass_mailing.models.mailing')
    def test_tracking_url_token(self):
        """ Test tracking of mails linked to a mailing trace: should set the
        trace as opened. """
        mailing = self.test_mailing_on_lists.with_env(self.env)
        with self.mock_mail_gateway(mail_unlink_sent=False):
            mailing.action_send_mail()

        mail = self._find_mail_mail_wrecord(self.test_contact)
        mail_id_int = mail.id
        mail_tracking_url = mail._get_tracking_url()
        mailing_trace = mail.mailing_trace_ids
        self.assertEqual(mail.state, 'sent')
        self.assertEqual(len(mailing_trace), 1)
        self.assertFalse(mailing_trace.open_datetime)
        self.assertEqual(mailing_trace.trace_status, 'sent')
        mail.unlink()  # the mail might be removed during the email sending
        self.env.flush_all()

        with freeze_time(self._reference_now):
            response = self.url_open(mail_tracking_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mailing_trace.open_datetime, self._reference_now)
        self.assertEqual(mailing_trace.trace_status, 'open')

        track_url = werkzeug.urls.url_join(
            mailing.get_base_url(),
            f'mail/track/{mail_id_int}/fake_token/blank.gif'
        )
        response = self.url_open(track_url)
        self.assertEqual(response.status_code, 400)
