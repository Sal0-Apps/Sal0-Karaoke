# 🛡️ Política de Segurança (v4.0.0)

## Versões com Suporte de Segurança

Apenas a versão mais recente e oficial do **Sal0 Karaokê** recebe correções e patches de segurança ativos.

| Versão | Status de Suporte | Observação |
|---|---|---|
| **v4.0.0 (atual)** | 🟢 **Ativo (Suportado)** | Única release oficial mantida no repositório. |

---

## 🔒 Práticas de Segurança e Privacidade

- **Processamento 100% Local**: O Sal0 Karaokê não transmite áudios, vídeos, legendas ou dados pessoais para nenhum servidor externo ou serviço em nuvem.
- **Isolamento de Credenciais**: Arquivos contendo tokens e chaves privadas (`.env_deploy`, `.env`, `*.token`) são expressamente ignorados pelo `.gitignore` e `.dockerignore`.
- **Criptografia de Senhas**: As senhas dos usuários são armazenadas em hash seguro **PBKDF2-HMAC-SHA256** com 100.000 iterações e Salt aleatório individual.
- **Proteção contra Brute-Force**: Tentativas de login são monitoradas, aplicando bloqueio temporário de 5 minutos após 10 falhas consecutivas.
- **Expiração de Sessões (TTL)**: Sessões ativas expiram automaticamente para proteger acessos em ambientes compartilhados.

---

## 📢 Reportando Vulnerabilidades

Se você identificou uma vulnerabilidade de segurança no Sal0 Karaokê:

1. **NÃO abra uma issue pública** com os detalhes da vulnerabilidade.
2. Envie um relatório privado abrindo um **GitHub Security Advisory**:
   - Acesse no repositório: `Security` > `Advisories` > `New draft security advisory`
3. Inclua no relatório:
   - Descrição detalhada do problema
   - Passos claros para reprodução
   - Impacto potencial estimado

Responderemos em até 48 horas e aplicaremos a correção na próxima atualização da v4.0.0.
