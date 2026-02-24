# n8n Workflow — Voice Commander License

## Workflow: "Voice Commander License"

Acionar via Stripe webhook → gerar chave → enviar email ao cliente.

---

## Nodes

### 1. Stripe Trigger
- **Evento:** `checkout.session.completed` + `invoice.paid`
- **URL:** Copiar da aba Trigger do n8n após criar o workflow
- Configurar no Stripe Dashboard → Developers → Webhooks

### 2. Code Node (JavaScript)

```javascript
const crypto = require('crypto');

const SECRET = $env.LICENSE_SECRET; // env var no n8n
const days = 30;

const expiry = new Date(Date.now() + days * 24 * 60 * 60 * 1000)
    .toISOString().split('T')[0]; // "2026-03-26"

const expiry_b64 = Buffer.from(expiry).toString('base64url');
const sig = crypto.createHmac('sha256', SECRET)
    .update(expiry).digest('hex').slice(0, 12);

const key = `vc-${expiry_b64}-${sig}`;
const email = $input.item.json.customer_email || $input.item.json.customer_details?.email;

return [{
    json: {
        key,
        expiry,
        email,
        days,
    }
}];
```

### 3. Send Email Node (Gmail ou SMTP)

- **Para:** `{{ $json.email }}`
- **Assunto:** `Seu acesso ao Voice Commander — JP Labs`
- **Body (HTML):**

```html
<p>Olá!</p>

<p>Aqui estão suas credenciais para o Voice Commander:</p>

<p><strong>🔑 Chave de licença:</strong><br>
<code>{{ $json.key }}</code><br>
<em>(válida por {{ $json.days }} dias — expira em {{ $json.expiry }})</em></p>

<p><strong>📥 Download:</strong><br>
<a href="https://github.com/thejplabs/voice-commander/releases/latest">
VoiceCommanderSetup.exe
</a></p>

<p>Após instalar, o app vai pedir sua chave de licença e sua chave do Google Gemini.</p>

<p><strong>Gemini API Key (gratuita):</strong><br>
<a href="https://aistudio.google.com/apikey">aistudio.google.com/apikey</a></p>

<hr>
<p><small>JP Labs Creative Studio · voice.jplabs.ai</small></p>
```

---

## Env Vars no n8n

Adicionar em Settings → Environment Variables:

```
LICENSE_SECRET = jp-labs-vc-secret-2026
```

> ⚠️ Este secret DEVE ser idêntico ao `_K` em `voice.py`. Se mudar aqui, atualizar lá também.

---

## Stripe Setup

1. Criar produto: "Voice Commander — Mensal" ($5/mês, subscription)
2. Criar checkout link (hosted checkout)
3. Dashboard → Developers → Webhooks → Add endpoint
   - URL: URL do Stripe Trigger node do n8n
   - Eventos: `checkout.session.completed`, `invoice.paid`
4. Copiar Webhook Secret → adicionar no Stripe Trigger node

---

## Teste local

```bash
cd C:\Users\joaop\voice-commander
python scripts/generate_license_key.py --days 30
# Output:
# Chave: vc-MjAyNi0wMy0yNg-a3f9b2c1d4e5
# Expiry: 2026-03-26 (30 dias)
# Auto-validação: Válida até 2026-03-26

python scripts/generate_license_key.py --validate "vc-MjAyNi0wMy0yNg-a3f9b2c1d4e5"
# Output:
# [VÁLIDA] Válida até 2026-03-26
```
