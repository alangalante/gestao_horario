# Meu Ponto

Aplicação local para importar espelhos de ponto em PDF, acompanhar presença e calcular saldos mensal e trimestral.

## Executar

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload
```

Acesse `http://127.0.0.1:8000`.

## Primeiro uso

1. Configure a carga esperada de cada dia da semana (em minutos).
2. Informe o mês inicial do ciclo trimestral e eventual saldo anterior.
3. Importe o PDF sempre que desejar atualizar as marcações.

Os dados ficam em `data/ponto.db`; os PDFs importados são preservados em `data/uploads/` para auditoria.

## Testes

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

## Executar no Rancher Desktop

O Docker CLI deve estar usando o contexto `rancher-desktop`.

```bash
docker context use rancher-desktop
docker compose up --build -d
```

A aplicação ficará disponível em `http://127.0.0.1:8000` e será reiniciada
automaticamente junto com o Rancher Desktop. Para acompanhar:

```bash
docker compose ps
docker compose logs -f meu-ponto
```

Para parar sem apagar os dados:

```bash
docker compose down
```

O diretório local `data/` é montado em `/app/data` dentro do container. Por
isso, recriar ou atualizar o container não apaga o banco, as configurações nem
os PDFs importados. Faça backup periódico dessa pasta.

