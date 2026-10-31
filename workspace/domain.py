from datetime import datetime, timedelta, time
from decimal import Decimal
from django.db.models import Sum
from django.utils import timezone
from .models import *

def money(value):
    return 'R$ ' + f'{value:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')

def total(queryset, field):
    return queryset.aggregate(value=Sum(field))['value'] or Decimal('0')

def series(items):
    peak = max([float(value) for label,value in items] + [1])
    return [{'label':label, 'value':float(value), 'display':money(value), 'percent':round(float(value) / peak * 100, 2)} for label,value in items]

def panel_item(obj, title, subtitle, value='', status=''):
    return {'pk':obj.pk, 'title':title, 'subtitle':subtitle, 'value':value, 'status':status}

def config(model, label, singular, icon, columns, headers, search, status=None, help=''):
    return {'model':model, 'label':label, 'new_label':singular, 'icon':icon, 'columns':columns, 'headers':headers, 'search':search, 'status':status, 'choices':list(model._meta.get_field(status).choices) if status else [], 'help':help, 'numeric':[i for i,field in enumerate(columns) if field in ('value','amount','price','balance','opening_balance','duration','limit','spent')]}


REGISTRY = {
 'transactions':config(Transaction,'Lançamentos','Novo lançamento','⇄',['title','account','kind','amount','date','status'],['Descrição','Conta','Tipo','Valor','Data','Status'],['title','account__name'],status='status',help='Somente lançamentos efetivados alteram o saldo. Valores devem ser positivos; o tipo define entrada ou saída.'),
 'accounts':config(Account,'Contas','Nova conta','▣',['name','opening_balance','balance'],['Conta','Saldo inicial','Saldo atual'],['name'],help='O saldo atual combina o saldo inicial com os lançamentos efetivados.'),
 'budgets':config(Budget,'Orçamentos','Novo orçamento','◴',['category','month','limit','spent'],['Categoria','Mês','Limite','Utilizado'],['category'],help='Um orçamento por categoria e mês. Considera apenas saídas efetivadas.'),
}

def dashboard_data(user):
    today = timezone.localdate()
    tx = Transaction.objects.filter(owner=user).select_related('account')
    paid = tx.filter(status='paid')
    month = paid.filter(date__year=today.year,date__month=today.month)
    income = total(month.filter(kind='income'),'amount')
    expense = total(month.filter(kind='expense'),'amount')
    accounts = list(Account.objects.filter(owner=user))
    balance = sum((a.balance for a in accounts),Decimal('0'))
    categories = [(label,total(month.filter(kind='expense',category=key),'amount')) for key,label in Transaction.CATEGORIES]
    budgets = Budget.objects.filter(owner=user,month=today.replace(day=1))
    over = sum(1 for b in budgets if b.spent > b.limit)
    return {'today':today,'heading':'Seu dinheiro, com clareza.','insight':('1 categoria acima do orçamento neste mês.' if over == 1 else f'{over} categorias acima do orçamento neste mês.') if over else 'Acompanhe seu saldo e escolha o próximo movimento.', 'empty':not accounts and not tx.exists(),'metrics':[
      {'label':'Saldo disponível','value':money(balance),'note':f'Em {len(accounts)} contas cadastradas'},
      {'label':'Entradas do mês','value':money(income),'note':'Somente valores efetivados'},
      {'label':'Saídas do mês','value':money(expense),'note':'Somente valores efetivados'},
      {'label':'Resultado do mês','value':money(income-expense),'note':today.strftime('Referência: %m/%Y')},
    ], 'chart_title':'Para onde vai o dinheiro','chart_subtitle':'Saídas efetivadas por categoria no mês atual','chart_legend':'Valor em reais','series':series(categories),'panels':[
      {'title':'Últimos movimentos','subtitle':'Valores persistidos, sem estimativas','kind':'transactions','items':[panel_item(t,t.title,f'{t.account.name} · {t.date:%d/%m}',('+' if t.kind=='income' else '−')+money(t.amount),t.get_status_display()) for t in tx[:6]]},
      {'title':'Orçamento do mês','subtitle':'Gasto efetivado em relação ao limite','kind':'budgets','items':[panel_item(b,b.get_category_display(),f'Limite: {money(b.limit)}',money(b.spent),'Acima do limite' if b.spent>b.limit else 'Dentro do limite') for b in budgets[:6]]},
    ]}

def seed_data(user):
    today = timezone.localdate()
    first = today.replace(day=1)
    a = Account.objects.create(owner=user,name='Conta principal',opening_balance=Decimal('8500'))
    b = Account.objects.create(owner=user,name='Reserva do estúdio',opening_balance=Decimal('12000'))
    rows = [('Projeto Horizonte','income','services','6800','paid'),('Identidade Aurora','income','services','4200','paid'),('Assinaturas do estúdio','expense','software','389.90','paid'),('Equipe de produção','expense','people','3200','paid'),('Campanha de outubro','expense','marketing','1250','paid'),('Internet e estrutura','expense','operations','680','paid'),('Licença de fotografia','expense','software','180','paid'),('Consultoria Nexo','income','services','2800','pending')]
    for i,(title,kind,category,amount,status) in enumerate(rows):
        Transaction.objects.create(owner=user,title=title,account=a,kind=kind,category=category,amount=Decimal(amount),date=first+timedelta(days=min(i*3,today.day-1)),status=status)
    for category,limit in [('software','700'),('people','4500'),('marketing','1000'),('operations','1500')]:
        Budget.objects.create(owner=user,category=category,month=first,limit=Decimal(limit))
