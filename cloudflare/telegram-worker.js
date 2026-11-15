/**
 * Telegram webhook router for India Stock Radar.
 * Cloudflare Worker Free receives commands; GitHub Actions runs Python scans.
 */
const DEFAULT_REPOSITORY = "Abhilash-nallam/stock-screener";
const DEFAULT_BRANCH = "new";
const WORKFLOW_FILE = "telegram-commands.yml";

const MENU = {
  inline_keyboard: [
    [
      { text: "📊 Fetch 250 stocks", callback_data: "scan:250" },
      { text: "📈 Fetch 500 stocks", callback_data: "scan:500" }
    ],
    [
      { text: "🔄 Refresh NSE", callback_data: "refresh:nse" },
      { text: "🔄 Refresh BSE", callback_data: "refresh:bse" }
    ],
    [{ text: "🔄 Refresh NSE + BSE", callback_data: "refresh:all" }],
    [{ text: "📋 Universe status", callback_data: "status" }],
    [{ text: "❔ Help", callback_data: "help" }]
  ]
};

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" }
  });
}

async function telegramApi(env, method, payload) {
  const response = await fetch(
    `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload || {})
    }
  );
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    throw new Error(data.description || `Telegram ${method} failed (HTTP ${response.status})`);
  }
  return data.result;
}

async function sendMessage(env, chatId, text, extra = {}) {
  return telegramApi(env, "sendMessage", {
    chat_id: String(chatId),
    text,
    disable_web_page_preview: true,
    ...extra
  });
}

async function showMenu(env, chatId, intro = true) {
  const text = intro
    ? "<b>🇮🇳 INDIA STOCK RADAR</b>\nChoose an action. Scans run on GitHub's cloud runner and the report returns here.\n\nCommands: /fetch 250, /fetch 500, /refresh_nse, /refresh_bse, /refresh_all, /status"
    : "<b>Choose scan size</b>\nSelect how many NSE + BSE stocks to scan.";
  await sendMessage(env, chatId, text, {
    parse_mode: "HTML",
    reply_markup: MENU
  });
}

async function dispatchJob(env, chatId, command, stockLimit = "250") {
  if (!env.GITHUB_ACTIONS_TOKEN) throw new Error("GitHub Actions token is not configured in Cloudflare Worker secrets.");
  const repository = env.GITHUB_REPOSITORY || DEFAULT_REPOSITORY;
  const response = await fetch(
    `https://api.github.com/repos/${repository}/actions/workflows/${WORKFLOW_FILE}/dispatches`,
    {
      method: "POST",
      headers: {
        "Accept": "application/vnd.github+json",
        "Authorization": `Bearer ${env.GITHUB_ACTIONS_TOKEN}`,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "india-stock-radar-cloudflare-worker",
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        ref: DEFAULT_BRANCH,
        inputs: {
          command,
          stock_limit: String(stockLimit)
        }
      })
    }
  );
  if (response.status !== 204) {
    const detail = await response.text();
    throw new Error(`GitHub could not start the scan workflow (HTTP ${response.status}). Check the fine-grained token's Actions: Read and write permission. ${detail.slice(0, 400)}`);
  }
}

async function queueJob(env, chatId, command, stockLimit) {
  const labels = {
    scan: `${stockLimit}-stock scan`,
    refresh_nse: "NSE universe refresh",
    refresh_bse: "BSE universe refresh",
    refresh_all: "NSE + BSE universe refresh",
    status: "universe status check"
  };
  await dispatchJob(env, chatId, command, stockLimit);
  await sendMessage(
    env,
    chatId,
    `⏳ <b>${labels[command] || "Request"} queued successfully.</b>\nGitHub's free cloud runner is starting the Python task. The result will be sent here automatically.`,
    { parse_mode: "HTML" }
  );
}

async function answerCallback(env, callbackId, text = "Request received") {
  if (!callbackId) return;
  await telegramApi(env, "answerCallbackQuery", {
    callback_query_id: callbackId,
    text
  });
}

async function runAction(env, chatId, action) {
  if (action === "help" || action === "menu") {
    await showMenu(env, chatId, true);
    return;
  }
  if (action === "scan") {
    await showMenu(env, chatId, false);
    return;
  }
  if (action === "scan:250" || action === "scan:500") {
    await queueJob(env, chatId, "scan", action.split(":")[1]);
    return;
  }
  if (action === "refresh:nse") {
    await queueJob(env, chatId, "refresh_nse");
    return;
  }
  if (action === "refresh:bse") {
    await queueJob(env, chatId, "refresh_bse");
    return;
  }
  if (action === "refresh:all") {
    await queueJob(env, chatId, "refresh_all");
    return;
  }
  if (action === "status") {
    await queueJob(env, chatId, "status");
    return;
  }
  await sendMessage(env, chatId, "I did not recognise that command. Send /help for controls.");
}

async function handleMessage(env, message) {
  const chatId = String(message?.chat?.id || "");
  if (!chatId || chatId !== String(env.TELEGRAM_CHAT_ID || "")) return;
  const raw = String(message?.text || "").trim();
  if (!raw) return;
  const parts = raw.split(/\s+/);
  const command = parts[0].split("@")[0].toLowerCase();

  if (command === "/start" || command === "/help") {
    await showMenu(env, chatId, true);
  } else if (command === "/menu") {
    await showMenu(env, chatId, true);
  } else if (command === "/scan" || command === "/fetch") {
    if (parts.length === 1) {
      await showMenu(env, chatId, false);
      return;
    }
    const limit = parts[1];
    if (limit !== "250" && limit !== "500") {
      await sendMessage(env, chatId, "Use /fetch 250 or /fetch 500.");
      return;
    }
    await queueJob(env, chatId, "scan", limit);
  } else if (command === "/refresh_nse") {
    await queueJob(env, chatId, "refresh_nse");
  } else if (command === "/refresh_bse") {
    await queueJob(env, chatId, "refresh_bse");
  } else if (command === "/refresh_all" || command === "/refresh") {
    await queueJob(env, chatId, "refresh_all");
  } else if (command === "/status" || command === "/universe") {
    await queueJob(env, chatId, "status");
  } else {
    await sendMessage(env, chatId, "Unknown command. Send /help to see available controls.");
  }
}

async function handleCallback(env, callback) {
  const chatId = String(callback?.message?.chat?.id || "");
  if (!chatId || chatId !== String(env.TELEGRAM_CHAT_ID || "")) {
    await answerCallback(env, callback?.id, "Not authorised");
    return;
  }
  await answerCallback(env, callback?.id);
  await runAction(env, chatId, String(callback?.data || ""));
}

async function registerWebhook(request, env) {
  if (!env.SETUP_KEY || request.headers.get("X-Setup-Key") !== env.SETUP_KEY) {
    return json({ ok: false, error: "Unauthorised" }, 401);
  }
  const body = await request.json().catch(() => ({}));
  let webhookUrl;
  try {
    webhookUrl = new URL(body.webhook_url);
  } catch {
    return json({ ok: false, error: "Provide a valid HTTPS webhook_url." }, 400);
  }
  if (webhookUrl.protocol !== "https:" || !webhookUrl.pathname.endsWith("/telegram/webhook")) {
    return json({ ok: false, error: "Webhook URL must be HTTPS and end in /telegram/webhook." }, 400);
  }
  const secret = String(env.TELEGRAM_WEBHOOK_SECRET || "");
  if (!/^[A-Za-z0-9_-]{1,256}$/.test(secret)) {
    return json({ ok: false, error: "TELEGRAM_WEBHOOK_SECRET must use 1-256 letters, digits, underscores or hyphens." }, 400);
  }
  const result = await telegramApi(env, "setWebhook", {
    url: webhookUrl.toString(),
    secret_token: secret,
    allowed_updates: ["message", "callback_query"],
    drop_pending_updates: false
  });
  await telegramApi(env, "setMyCommands", {
    commands: [
      { command: "start", description: "Open stock radar controls" },
      { command: "fetch", description: "Fetch /fetch 250 or /fetch 500" },
      { command: "scan", description: "Alias for fetch stock scan" },
      { command: "refresh_nse", description: "Refresh NSE universe" },
      { command: "refresh_bse", description: "Refresh BSE universe" },
      { command: "refresh_all", description: "Refresh both exchange universes" },
      { command: "status", description: "Show cached universe counts" },
      { command: "help", description: "Show bot help and buttons" }
    ]
  });
  return json({ ok: true, webhook_registered: result === true });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health" && request.method === "GET") {
      return json({ ok: true, service: "india-stock-radar-telegram-webhook" });
    }

    if (url.pathname === "/admin/register" && request.method === "POST") {
      try {
        return await registerWebhook(request, env);
      } catch (error) {
        return json({ ok: false, error: error.message }, 502);
      }
    }

    if (url.pathname !== "/telegram/webhook" || request.method !== "POST") {
      return new Response("Not found", { status: 404 });
    }

    const suppliedSecret = request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "";
    if (!env.TELEGRAM_WEBHOOK_SECRET || suppliedSecret !== env.TELEGRAM_WEBHOOK_SECRET) {
      return new Response("Forbidden", { status: 403 });
    }

    let update;
    try {
      update = await request.json();
    } catch {
      return new Response("Bad Request", { status: 400 });
    }

    try {
      if (update.message) {
        await handleMessage(env, update.message);
      } else if (update.callback_query) {
        await handleCallback(env, update.callback_query);
      }
    } catch (error) {
      console.error("Webhook update processing failed:", error.message);
      const chatId = String(update?.message?.chat?.id || update?.callback_query?.message?.chat?.id || "");
      if (chatId && chatId === String(env.TELEGRAM_CHAT_ID || "")) {
        try {
          await sendMessage(env, chatId, "⚠️ Could not queue that request. Check Cloudflare Worker secrets and the GitHub Actions token.");
        } catch (sendError) {
          console.error("Could not send bot error notice:", sendError.message);
        }
      }
    }

    // Acknowledge Telegram after the small webhook/dispatch operation completes.
    return new Response("OK", { status: 200 });
  }
};
