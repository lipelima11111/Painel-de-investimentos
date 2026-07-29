# Painel de Investimentos

Painel local de renda fixa brasileira. Você cadastra seus investimentos, e ele
calcula **quanto rende por dia** e **quanto você vai ter no futuro** usando as
taxas oficiais do Banco Central (CDI, Selic, IPCA, TR, poupança).

Tudo em Python (Flask + SQLite), front em HTML/CSS/JS puro. Roda offline depois
do primeiro acesso — as séries do BACEN ficam em cache no disco.

---

## Instalação

Precisa de Python 3.10 ou superior.

```
pip install -r requirements.txt
```

## Uso

```
python app.py
```

O programa sobe o servidor e **abre o navegador sozinho** na página do painel.

Opções:

| Flag              | Efeito                                          |
| ----------------- | ------------------------------------------------ |
| `--porta 8000`    | usa uma porta específica (padrão: 5000)         |
| `--sem-navegador` | não abre o navegador                            |
| `--debug`         | recarrega o código a cada alteração             |
| `--producao`      | usa o Waitress em vez do servidor de desenvolvimento |

No Windows dá para clicar duas vezes em `iniciar.bat`.

Seus dados ficam em `dados/investimentos.db` (SQLite). O cache das taxas fica
em `dados/cache_bacen.json`. Para começar do zero, apague o `.db`.

### Rodando os testes

```
pytest testes/ -v
```

Cobre o calendário de dias úteis, os invariantes do motor de cálculo (base 252,
fórmula do %CDI, tabela de IR/IOF), a poupança histórica, resgates, come-cotas
e a API (validação, CSRF, rateio de custódia).

---

## O que dá para cadastrar

**Produtos:** CDB, RDB, LC, LCI, LCA, LIG, CRI/CRA, Debênture (comum e
incentivada), Tesouro Selic, Tesouro Prefixado, Tesouro IPCA+, Poupança e
Fundo DI.

**Formas de rendimento:**

| Indexador          | Como se informa           | Exemplo             |
| ------------------ | -------------------------- | -------------------- |
| Pós-fixado % CDI   | percentual do CDI          | `110` = 110% do CDI |
| CDI + spread       | pontos ao ano acima do CDI | `2` = CDI + 2% a.a. |
| Prefixado          | taxa anual travada         | `12,5% a.a.`        |
| IPCA + spread      | juro real anual            | `IPCA + 6,8% a.a.`  |
| Selic + spread     | ágio/deságio do Tesouro    | `Selic + 0,05% a.a.`|
| Poupança           | sem taxa (regra oficial)   | —                   |

Cada investimento aceita **aporte mensal** — o painel trata cada aporte como um
lote separado, com a própria data de aplicação, para que IR e IOF saiam certos
por lote. Também é possível registrar **resgates** (parciais ou totais): eles
consomem os lotes mais antigos primeiro (FIFO) e realizam o IR/IOF na data do
resgate.

---

## As quatro telas

- **Carteira** — patrimônio de hoje, rendimento por dia útil, imposto se
  resgatar agora, evolução histórica, alocação por tipo e por indexador, a
  linha do tempo dos vencimentos e a tabela dos seus investimentos (ordenável
  por qualquer coluna).
- **Projeção** — para onde a carteira vai em 1 a 30 anos, com marcos ano a
  ano e um cenário de choque na Selic (+2 p.p. / −2 p.p.) para ver o quanto a
  projeção depende da taxa de hoje.
- **Simulador** — mesmo dinheiro, mesmo prazo, produtos diferentes: mostra qual
  ganha *depois* de IR e IOF. Inclui a conta de equivalência (quanto uma LCI
  isenta precisa pagar para empatar com um CDB tributado).
- **Como funciona** — a página que explica cada regra aplicada, para auditar o
  número em vez de confiar cegamente nele.

O KPI **"Desempenho vs. CDI"** na Carteira usa a taxa interna de retorno
(XIRR) do fluxo de caixa real — aportes, resgates e saldo atual — e compara
com o CDI acumulado no mesmo período. É a métrica correta quando há aporte
mensal: a rentabilidade simples (rendimento ÷ aportado) mistura dinheiro que
ficou anos com dinheiro que entrou mês passado, e pode fazer a poupança
parecer melhor que o Tesouro Selic quando não é.

---

## Como as contas são feitas

**Base 252.** Renda fixa brasileira só rende em dia útil. O calendário segue os
feriados nacionais da ANBIMA, incluindo os móveis (Carnaval, Sexta-feira Santa,
Corpus Christi) e a Consciência Negra a partir de 2024. A contagem de dias
úteis entre duas datas é O(1) — somas de prefixos por ano, em vez de percorrer
dia a dia — o que faz uma projeção de 30 anos rodar em milissegundos em vez de
segundos.

**Intervalo `[aplicação, resgate)`.** O dia da aplicação rende; o dia do resgate
não. Um prefixado de 12% a.a. mantido por 252 dias úteis dá exatamente 12%.

**% do CDI** usa a fórmula da B3/CETIP — `fator = 1 + TDI × (p/100)`, e **não**
`(1 + TDI)^p`. É a diferença entre bater e não bater com o extrato do banco.

**Spreads** capitalizam em base 252: `(1 + i)^(1/252)` por dia útil.

**IR regressivo** sobre o rendimento, por lote:

| Prazo do lote     | Alíquota |
| ------------------ | -------- |
| até 180 dias       | 22,5%    |
| 181 a 360 dias     | 20,0%    |
| 361 a 720 dias     | 17,5%    |
| acima de 720 dias  | 15,0%    |

LCI, LCA, LIG, CRI/CRA, debênture incentivada e poupança são isentos.

**IOF regressivo** incide sobre o rendimento nos resgates com menos de 30 dias,
antes do IR (96% no 1º dia até 0% no 30º).

**Come-cotas** de 15% no último dia útil de maio e novembro para Fundo DI. O
crédito do imposto já retido é rateado entre os lotes pelo rendimento de cada
um — um aporte de dois meses não herda a alíquota do aporte mais antigo.

**Custódia B3** no Tesouro Direto, com a taxa **vigente em cada data**: 0,30%
a.a. até jul/2019, 0,25% de ago/2019 a dez/2021 e 0,20% desde jan/2022. A
isenção sobre os primeiros R$ 10.000 em Tesouro Selic só passou a existir em
**ago/2020** — uma posição de 2015 paga custódia sobre o saldo inteiro. A
isenção é **por conta na B3, não por título**: quem tem mais de um Tesouro
Selic ativo divide o benefício proporcionalmente ao valor aplicado em vez de
cada posição reivindicar os R$ 10.000 inteiros.

**Poupança:** duas regras convivem, e o painel escolhe pela **data do depósito**.

| Depósito | Regra | Série BACEN |
| --- | --- | --- |
| até 03/05/2012 | 0,5% a.m. composto com a TR, sempre | SGS 25 |
| a partir de 04/05/2012 | Lei 12.703 | SGS 195 |

Pela Lei 12.703, se a meta Selic passa de 8,5% a.a. vale 0,5% a.m.; se fica
igual ou abaixo, a base é a **mensalização de 70% da meta anual** —
`(1 + 0,70 × Selic)^(1/12) − 1`, e não 70% da Selic já mensalizada. Nos dois
casos a **TR compõe** com a remuneração básica, não é somada a ela. As duas
regras só coincidem enquanto a Selic passa de 8,5%: entre out/2017 e ago/2021
a poupança antiga rendeu mais que o dobro da nova, e um dia de diferença na
data do depósito vale hoje ~12% de saldo acumulado.

Depósitos feitos em 29, 30 ou 31 têm data-base no dia 1º do mês seguinte,
conforme a regra do CMN. Só credita no aniversário mensal.

**IPCA+** segue a convenção de VNA da ANBIMA/Tesouro Nacional: o índice de
referência vira no **dia 15** de cada mês, e o IPCA do mês *m* é acumulado
pro-rata em **dias úteis** entre 15/*m* e 15/(*m*+1). É por isso que uma NTN-B
que vence em 15/08 paga exatamente a inflação fechada até julho — a defasagem
é de meio mês e não coincide com o mês civil.

**FGC:** o painel avisa quando a soma por instituição passa de R$ 250.000.

**Resgates:** parciais ou totais, com FIFO nos lotes e IR/IOF realizados na
data do resgate. Um resgate total encerra a posição (ela some da alocação
ativa, mas o ganho realizado continua contando na rentabilidade da carteira).

### Do que vem cada taxa

| Dado                    | Fonte              | Cobertura     |
| ----------------------- | ------------------ | ------------- |
| CDI diário              | BACEN SGS série 12  | desde 1986   |
| Selic diária            | BACEN SGS série 11  | desde 1986   |
| Selic meta (degraus do Copom) | BACEN SGS série 432 | desde 1996 |
| IPCA mensal             | BACEN SGS série 433 | desde 1980   |
| TR                      | BACEN SGS série 226 | desde 1991   |
| Poupança — regra nova   | BACEN SGS série 195 | desde 04/05/2012 |
| Poupança — regra antiga | BACEN SGS série 25  | desde 1991   |
| IPCA e Selic futuros    | Boletim Focus (Olinda) | projeção  |

Até hoje o cálculo usa a taxa que **de fato** ocorreu, dia a dia. Do dia de hoje
em diante, projeta com o CDI/Selic esperados — ajustáveis por um cenário de
choque — e o IPCA esperado pelo Focus.

Nada do passado usa a taxa corrente. Quando falta publicação para um dia útil já
ocorrido (falha de rede, buraco na série), o trecho é reconstruído pela **meta
Selic vigente naquela data** e o painel mostra um alerta dizendo exatamente qual
série e qual ano — reconstruir é aceitável, reconstruir em silêncio não.

O cache das séries do BACEN é particionado **por ano civil**
(`sgs:12:2024`, por exemplo): anos fechados são baixados uma única vez (TTL de
60 dias) e só o ano corrente é revisitado (TTL de 6 horas). Isso evita
refazer o download da série inteira a cada dia novo ou a cada investimento
antigo cadastrado.

---

## Limitações (leia antes de decidir algo)

- **Não há marcação a mercado.** Prefixados e IPCA+ são calculados *na curva* —
  o valor mostrado é o de carregar até o vencimento, não o de vender hoje. Para
  pós-fixados (Tesouro Selic, CDB/LCI em % do CDI) isso equivale à realidade;
  para Tesouro Prefixado e IPCA+ **resgatados antes do vencimento** o preço real
  oscila com a curva de juros. Fechar essa lacuna exigiria a série de preços
  diários do [Tesouro Transparente](https://www.tesourotransparente.gov.br/ckan/dataset/precos-e-taxas-dos-titulos-publicos-federais),
  que é a fonte oficial e a melhor alternativa caso isso passe a importar.
- **A projeção não é previsão.** Ela repete a taxa esperada para frente
  (ajustável pelo cenário de choque na Selic). Se a Selic sair do previsto, o
  número sai junto.
- **Sem taxa de corretagem** além da custódia da B3.
- **Sem tributação de fundos de curto prazo** (carteira média abaixo de 365
  dias, come-cotas de 20% e IR de 22,5%/20%). O catálogo só tem fundo de longo
  prazo, onde o come-cotas é de 15%.
- **Ágio/deságio na compra de Tesouro Direto** não é modelado: o preço de
  entrada é o valor aplicado.
- Os dados ficam só na sua máquina. Não há login, nem envio para lugar nenhum.

O painel é uma ferramenta de acompanhamento e comparação, não recomendação de
investimento.

---

## Estrutura

```
app.py                 sobe o servidor e abre o navegador
painel/
  feriados.py          calendario de dias uteis (ANBIMA), contagem O(1)
  bacen.py              cliente das APIs do BACEN, cache por ano
  catalogo.py           produtos, indexadores, tabelas de IR/IOF, cenarios
  database.py           SQLite + validacao + resgates + rateio de custodia
  calculos.py            o motor: indice acumulado, lotes, impostos, XIRR
  api.py                 rotas JSON do Flask
  templates/index.html   a pagina
  static/css, static/js  estilo e graficos SVG (sem biblioteca externa)
dados/                 seu banco e o cache das taxas
testes/                pytest: calendario, motor, api
```

O motor mantém um **índice acumulado** de fatores diários. Assim qualquer lote
de aporte é avaliado em O(1) por `principal × índice_hoje / índice_do_aporte`,
o que deixa o IR e o IOF exatos por lote mesmo com centenas de aportes mensais.
A contagem de dias úteis também é O(1), então uma projeção de 30 anos com
vários investimentos permanece instantânea.
