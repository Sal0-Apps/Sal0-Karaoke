# Security Policy

## Versoes com Suporte de Seguranca

Apenas a versao mais recente do Sal0 Karaoke recebe patches de seguranca ativos.

| Versao | Suporte |
|--------|---------|
| 3.6.x (atual) | Sim |
| < 3.6.0 | Nao |

## Reportando Vulnerabilidades

Se voce descobriu uma vulnerabilidade de seguranca no Sal0 Karaoke:

1. **NAO abra uma issue publica** com detalhes da vulnerabilidade.
2. Envie um relatorio privado abrindo um **GitHub Security Advisory** neste repositorio:
   - Va em: Security > Advisories > New draft security advisory
3. Inclua no relatorio:
   - Descricao clara da vulnerabilidade
   - Passos para reproduzir
   - Impacto potencial
   - Sugestao de correcao (se tiver)

## O que esperamos de voce

- Nos dar tempo razoavel para corrigir antes de divulgar publicamente
- Nao explorar a vulnerabilidade alem do necessario para confirma-la
- Nao acessar dados de outros usuarios sem consentimento

## O que voce pode esperar de nos

- Confirmacao de recebimento em ate 48h
- Atualizacoes sobre o progresso da correcao
- Credito publico pelo relatorio (se desejar)

## Credenciais e Tokens

- **Nunca** commite tokens, senhas ou chaves no repositorio
- Use variaveis de ambiente ou arquivos locais listados no .gitignore
- O arquivo .env_deploy e um exemplo de armazenamento local seguro de credenciais

## Contato

Para duvidas de seguranca que nao se qualificam como vulnerabilidades, abra uma issue normal.
