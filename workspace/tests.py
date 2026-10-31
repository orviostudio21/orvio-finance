
import csv
from io import StringIO
from datetime import timedelta
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.forms.models import model_to_dict
from django.test import TestCase, Client as Browser
from django.urls import reverse
from django.utils import timezone
from .domain import REGISTRY, seed_data, dashboard_data
from .forms import form_for
from .models import *

class WorkspaceTests:
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('marina',password='A-strong-password-2026')
        cls.other = get_user_model().objects.create_user('rafael',password='A-strong-password-2026')
        seed_data(cls.user)
        seed_data(cls.other)

    def setUp(self):
        cache.clear()
        self.client.force_login(self.user)

    def test_private_routes_require_login(self):
        self.client.logout()
        for url in ['/', '/settings/', '/api/overview/']:
            self.assertEqual(self.client.get(url).status_code,302)

    def test_dashboard_and_api_render_real_data(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Orvio')
        self.assertNotRegex(response.content.decode(), r'height:[0-9]+,[0-9]+%')
        api = self.client.get('/api/overview/')
        self.assertEqual(api.status_code,200)
        self.assertEqual(len(api.json()['metrics']),4)

    def test_all_lists_details_and_forms_render(self):
        for kind,config in REGISTRY.items():
            obj = config['model'].objects.filter(owner=self.user).first()
            for url in [f'/records/{kind}/',f'/records/{kind}/new/',f'/records/{kind}/{obj.pk}/',f'/records/{kind}/{obj.pk}/edit/',f'/records/{kind}/{obj.pk}/delete/']:
                with self.subTest(url=url):
                    self.assertEqual(self.client.get(url).status_code,200)

    def test_foreign_objects_are_inaccessible(self):
        for kind,config in REGISTRY.items():
            obj = config['model'].objects.filter(owner=self.other).first()
            for suffix in ['', 'edit/', 'delete/']:
                url = f'/records/{kind}/{obj.pk}/'+suffix
                self.assertEqual(self.client.get(url).status_code,404)
                self.assertEqual(self.client.post(url,{}).status_code,404)
            self.assertTrue(config['model'].objects.filter(pk=obj.pk).exists())

    def test_foreign_relations_are_not_form_choices(self):
        for config in REGISTRY.values():
            model = config['model']
            obj = model(owner=self.user)
            form = form_for(model)(instance=obj,user=self.user)
            for field in form.fields.values():
                if hasattr(field,'queryset') and field.queryset is not None:
                    self.assertFalse(field.queryset.exclude(owner=self.user).exists())

    def test_owner_cannot_be_changed_by_post(self):
        kind,config = next(iter(REGISTRY.items()))
        obj = config['model'].objects.filter(owner=self.user).first()
        data = model_to_dict(obj)
        data['owner'] = self.other.pk
        for key,value in list(data.items()):
            if value is None:
                data[key] = ''
            elif hasattr(value,'isoformat'):
                data[key] = timezone.localtime(value).strftime('%Y-%m-%dT%H:%M') if isinstance(value,timezone.datetime) else value.isoformat()
        response = self.client.post(f'/records/{kind}/{obj.pk}/edit/',data)
        self.assertEqual(response.status_code,302)
        obj.refresh_from_db()
        self.assertEqual(obj.owner_id,self.user.pk)

    def test_csv_export_is_scoped(self):
        for kind,config in REGISTRY.items():
            response = self.client.get(f'/records/{kind}/export/')
            self.assertEqual(response.status_code,200)
            rows = list(csv.reader(StringIO(response.content.decode('utf-8-sig'))))
            self.assertEqual(len(rows),config['model'].objects.filter(owner=self.user).count()+1)

    def test_demo_is_idempotent_and_does_not_overwrite(self):
        counts = [c['model'].objects.filter(owner=self.user).count() for c in REGISTRY.values()]
        self.client.post('/demo/')
        self.assertEqual(counts,[c['model'].objects.filter(owner=self.user).count() for c in REGISTRY.values()])

    def test_new_account_starts_empty_and_can_seed(self):
        fresh = get_user_model().objects.create_user('new-account',password='Some-strong-pass-26')
        self.client.force_login(fresh)
        self.assertContains(self.client.get('/'),'Seu próximo capítulo')
        self.assertEqual(self.client.post('/demo/').status_code,302)
        self.assertTrue(all(c['model'].objects.filter(owner=fresh).exists() for c in REGISTRY.values()))

    def test_mutations_require_csrf(self):
        browser = Browser(enforce_csrf_checks=True)
        browser.force_login(self.user)
        self.assertEqual(browser.post('/demo/').status_code,403)

    def test_logout_is_post_only(self):
        self.assertEqual(self.client.get('/logout/').status_code,405)
        self.assertEqual(self.client.post('/logout/').status_code,302)

    def test_unknown_collections_404(self):
        self.assertEqual(self.client.get('/records/unknown/').status_code,404)

    def test_signup_rejects_weak_password(self):
        self.client.logout()
        response = self.client.post('/signup/',{'username':'weak','password1':'123','password2':'123'})
        self.assertEqual(response.status_code,200)
        self.assertFalse(get_user_model().objects.filter(username='weak').exists())

    def test_signup_and_login(self):
        self.client.logout()
        response = self.client.post('/signup/',{'username':'new-user','password1':'A-new-strong-pass-2026','password2':'A-new-strong-pass-2026'})
        self.assertEqual(response.status_code,302)
        self.client.post('/logout/')
        response = self.client.post('/login/',{'username':'new-user','password':'A-new-strong-pass-2026'})
        self.assertEqual(response.status_code,302)

    def test_password_change_preserves_session(self):
        response = self.client.post('/settings/',{'old_password':'A-strong-password-2026','new_password1':'Changed-strong-pass-26','new_password2':'Changed-strong-pass-26'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.get('/').status_code,200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Changed-strong-pass-26'))

    def test_login_rate_limit(self):
        self.client.logout()
        for i in range(20):
            self.client.post('/login/',{'username':'absent','password':'wrong'})
        self.assertEqual(self.client.post('/login/',{'username':'absent','password':'wrong'}).status_code,429)

    def test_health_checks_database(self):
        self.assertEqual(self.client.get('/health/').json(),{'status':'ok'})


class FinanceTests(WorkspaceTests, TestCase):
    def test_balance_counts_only_paid_and_preserves_cents(self):
        account = Account.objects.create(owner=self.user,name='Precisão',opening_balance=Decimal('10.10'))
        for kind,amount,status in [('income','5.25','paid'),('expense','2.17','paid'),('expense','100','pending')]:
            Transaction.objects.create(owner=self.user,title='Teste',account=account,kind=kind,category='other',amount=Decimal(amount),status=status)
        self.assertEqual(account.balance,Decimal('13.18'))

    def test_budget_ignores_pending_and_income(self):
        account = Account.objects.filter(owner=self.user).first()
        today = timezone.localdate()
        budget = Budget(owner=self.user,category='other',month=today,limit=Decimal('100'))
        budget.full_clean()
        budget.save()
        self.assertEqual(budget.month.day,1)
        for kind,amount,status in [('expense','32.75','paid'),('expense','200','pending'),('income','80','paid')]:
            Transaction.objects.create(owner=self.user,title='Teste',account=account,kind=kind,category='other',amount=Decimal(amount),status=status)
        self.assertEqual(budget.spent,Decimal('32.75'))

    def test_duplicate_monthly_budget_is_rejected(self):
        existing = Budget.objects.filter(owner=self.user).first()
        form = form_for(Budget)({'category':existing.category,'month':existing.month.replace(day=15).isoformat(),'limit':'800'},user=self.user)
        self.assertFalse(form.is_valid())

    def test_nonpositive_transaction_is_rejected(self):
        account = Account.objects.filter(owner=self.user).first()
        for value in ['0','-1']:
            form = form_for(Transaction)({'title':'Inválido','account':account.pk,'kind':'expense','category':'other','amount':value,'date':'2026-11-01','status':'paid'},user=self.user)
            self.assertFalse(form.is_valid())

    def test_foreign_account_is_rejected(self):
        account = Account.objects.filter(owner=self.other).first()
        form = form_for(Transaction)({'title':'Inválido','account':account.pk,'kind':'expense','category':'other','amount':'10','date':'2026-11-01','status':'paid'},user=self.user)
        self.assertFalse(form.is_valid())

    def test_transaction_lifecycle_recalculates_balance(self):
        account = Account.objects.create(owner=self.user,name='Fluxo',opening_balance=Decimal('100'))
        data = {'title':'Pagamento','account':account.pk,'kind':'expense','category':'other','amount':'20.15','date':timezone.localdate().isoformat(),'status':'pending'}
        self.assertEqual(self.client.post('/records/transactions/new/',data).status_code,302)
        obj = Transaction.objects.get(owner=self.user,title='Pagamento')
        self.assertEqual(account.balance,Decimal('100'))
        data['status'] = 'paid'
        self.assertEqual(self.client.post(f'/records/transactions/{obj.pk}/edit/',data).status_code,302)
        self.assertEqual(account.balance,Decimal('79.85'))
        self.client.post(f'/records/transactions/{obj.pk}/delete/')
        self.assertEqual(account.balance,Decimal('100'))

    def test_account_with_transactions_is_protected(self):
        account = Transaction.objects.filter(owner=self.user).first().account
        self.client.post(f'/records/accounts/{account.pk}/delete/')
        self.assertTrue(Account.objects.filter(pk=account.pk).exists())
