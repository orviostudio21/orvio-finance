from datetime import timedelta
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone

class Owned(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, editable=False)
    created_at = models.DateTimeField('criado em', auto_now_add=True)
    class Meta:
        abstract = True
        ordering = ['-created_at', '-pk']

    def validate_owner(self, *relations):
        for relation in relations:
            if getattr(self, relation+'_id', None) and getattr(self, relation).owner_id != self.owner_id:
                raise ValidationError({relation:'O registro deve pertencer ao seu espaço.'})

class Event(Owned):
    description = models.CharField('ação', max_length=300)
    def __str__(self):
        return self.description


class Account(Owned):
    name = models.CharField('conta', max_length=100)
    opening_balance = models.DecimalField('saldo inicial', max_digits=12, decimal_places=2, default=Decimal('0'))
    notes = models.TextField('observações', blank=True, max_length=2000)
    class Meta(Owned.Meta):
        constraints = [models.UniqueConstraint(fields=['owner','name'], name='unique_account_name')]
    def __str__(self):
        return self.name
    @property
    def balance(self):
        from django.db.models import Sum
        paid = self.transaction_set.filter(status='paid')
        return self.opening_balance + (paid.filter(kind='income').aggregate(v=Sum('amount'))['v'] or Decimal('0')) - (paid.filter(kind='expense').aggregate(v=Sum('amount'))['v'] or Decimal('0'))

class Transaction(Owned):
    KINDS = [('income','Entrada'),('expense','Saída')]
    STATUS = [('paid','Efetivado'),('pending','Pendente')]
    CATEGORIES = [('sales','Vendas'),('services','Serviços'),('people','Equipe'),('software','Software'),('marketing','Marketing'),('operations','Operação'),('other','Outros')]
    title = models.CharField('descrição', max_length=140)
    account = models.ForeignKey(Account, verbose_name='conta', on_delete=models.PROTECT)
    kind = models.CharField('tipo', choices=KINDS, max_length=10)
    category = models.CharField('categoria', choices=CATEGORIES, max_length=15)
    amount = models.DecimalField('valor', max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    date = models.DateField('data', default=timezone.localdate)
    status = models.CharField('status', choices=STATUS, max_length=10, default='paid')
    notes = models.TextField('observações', blank=True, max_length=2000)
    class Meta(Owned.Meta):
        ordering = ['-date','-pk']
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='positive_transaction_amount')]
    def clean(self):
        self.validate_owner('account')
    def __str__(self):
        return self.title

class Budget(Owned):
    category = models.CharField('categoria', choices=Transaction.CATEGORIES, max_length=15)
    month = models.DateField('mês de referência', default=timezone.localdate, help_text='Qualquer dia será normalizado para o primeiro dia do mês.')
    limit = models.DecimalField('limite mensal', max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal('0.01'))])
    class Meta(Owned.Meta):
        constraints = [models.UniqueConstraint(fields=['owner','category','month'], name='unique_monthly_budget'), models.CheckConstraint(condition=Q(limit__gt=0), name='positive_budget_limit')]
    def clean(self):
        if self.month:
            self.month = self.month.replace(day=1)
    def __str__(self):
        return f'{self.get_category_display()} · {self.month:%m/%Y}'
    @property
    def spent(self):
        from django.db.models import Sum
        return Transaction.objects.filter(owner_id=self.owner_id,kind='expense',status='paid',category=self.category,date__year=self.month.year,date__month=self.month.month).aggregate(v=Sum('amount'))['v'] or Decimal('0')
