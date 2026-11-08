import express from "express";
import { readWorkspaceConfig, writeWorkspaceConfig } from "./server/workspaceConfig.ts";
import path from "path";
import { createServer as createViteServer } from "vite";
import { spawn } from "child_process";
import { createProxyMiddleware } from "http-proxy-middleware";
import { createFengshenAuthProxy } from "./server/fengshenAuthProxy.ts";
import { createDownloadProxy } from "./server/downloadProxy.ts";
import { acquireStartupLock, assertPortAvailable } from "./server/startupGuard.ts";
import { createLegacyBoundary } from "./server/legacyDownloadBoundary.ts";
import { deliveryDownloadAlias } from './server/deliveryDownloadAlias.ts';
import { extractSourceArchive } from './server/sourceArchive.ts';
import http from "node:http";
import fs from "fs";
import os from "os";
import multer from "multer";
import AdmZip from "adm-zip";
import * as XLSX from "xlsx";
import axios from "axios";
import FormData from "form-data";
import { randomBytes, randomUUID } from "node:crypto";

import cors from "cors";

import { Server as SocketIOServer } from "socket.io";

function getUploadSequence(wid: string): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  const dateStr = `${year}${month}${day}`;

  const baseDir = path.join(process.cwd(), "uploads", wid);
  let maxSeq = 0;

  if (fs.existsSync(baseDir)) {
    try {
      const dirs = fs.readdirSync(baseDir);
      for (const dir of dirs) {
        if (dir.startsWith(`upload_${dateStr}`)) {
          const seqStr = dir.slice(`upload_${dateStr}`.length);
          const seq = parseInt(seqStr, 10);
          if (!isNaN(seq) && seq > maxSeq) {
            maxSeq = seq;
          }
        }
      }
    } catch (e) {
      console.error(e);
    }
  }

  const nextSeq = maxSeq + 1;
  const seqStr = String(nextSeq).padStart(5, "0");
  return `${dateStr}${seqStr}`;
}

function ensureConfigExists() {
  const dataDir = path.resolve("data");
  if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
  }

  const configPath = path.join(dataDir, "config.json");
  if (!fs.existsSync(configPath)) {
    console.log("config.json not found. Creating a beautiful default config.json...");
    
    // Default config data
    const defaultRows = [
      {
        "城市": "上海",
        "团队名称": "浦东耀华站",
        "团队ID": "SH-PD-01",
        "安全基金": 50,
        "非蜂卡扣款": 100,
        "装备扣款": 150,
        "投诉": 100,
        "差评": 50,
        "违规虚假": 200,
        "物流责": 50,
        "不准时单": 20,
        "超时": 10,
        "T10": 30,
        "提前点送达": 50
      },
      {
        "城市": "北京",
        "团队名称": "朝阳大屯站",
        "团队ID": "BJ-CY-01",
        "安全基金": 50,
        "非蜂卡扣款": 100,
        "装备扣款": 150,
        "投诉": 100,
        "差评": 50,
        "违规虚假": 200,
        "物流责": 50,
        "不准时单": 20,
        "超时": 10,
        "T10": 30,
        "提前点送达": 50
      }
    ];

    fs.writeFileSync(configPath, JSON.stringify(defaultRows, null, 2), "utf-8");
    console.log("Successfully created default config.json at:", configPath);
  }

  const localDownloadsDir = path.resolve("backend", ".local_downloads");
  if (!fs.existsSync(localDownloadsDir)) {
    fs.mkdirSync(localDownloadsDir, { recursive: true });
  }
  const protectedRootsPath = path.join(localDownloadsDir, "protected_roots.json");
  if (!fs.existsSync(protectedRootsPath)) {
    fs.writeFileSync(
      protectedRootsPath,
      JSON.stringify({ roots: [path.resolve("outputs", "fengshen_downloads")] }),
      "utf-8",
    );
  }
}

async function startServer() {
  const app = express();
  app.use(cors());
  const localTestMode = process.env.LOCAL_TEST_MODE === "1";
  const PORT = Number(process.env.APP_PORT || (process.env.PORT === "8080" ? 3000 : process.env.PORT) || 3000);
  const backendPort = Number(process.env.BACKEND_PORT || 8009);
  if (![PORT, backendPort].every((port) => Number.isInteger(port) && port > 0 && port <= 65535) || PORT === backendPort) {
    throw new Error("Frontend and backend require distinct valid ports.");
  }
  const listenHost = process.env.HOST || "0.0.0.0";
  const backendUrl = `http://127.0.0.1:${backendPort}`;
  const lockFilePath = process.env.K_SERVICE
    ? path.join(os.tmpdir(), "payroll-server.lock")
    : path.join(process.cwd(), "backend", ".local_downloads", "server.lock");
  const releaseStartupLock = acquireStartupLock(lockFilePath);
  process.once("exit", releaseStartupLock);
  const server = http.createServer(app);
  // A local 1–2 GiB upload can exceed Node's five-minute request deadline.
  server.requestTimeout = 60 * 60 * 1000;
  try {
    await assertPortAvailable(backendPort, "127.0.0.1");
    // Own the frontend port before starting Python. A second launch must not
    // spawn a backend and discover the frontend conflict only afterwards.
    await new Promise<void>((resolve, reject) => {
      server.once("error", reject);
      server.listen({ port: PORT, host: listenHost, exclusive: true }, resolve);
    });
  } catch (error) {
    releaseStartupLock();
    server.close();
    throw error;
  }
  const proxySecret = randomBytes(32).toString("hex");
  const legacyBoundary = createLegacyBoundary();
  app.use(deliveryDownloadAlias(process.env.FENGSHEN_DOWNLOAD_ROOT || path.resolve('outputs/fengshen_downloads')));
  app.use(legacyBoundary.guardRequest);
  const legacyJson = () => [express.json(), legacyBoundary.guardBody];
  ensureConfigExists();

  // Only spawn python backend in production or if not already running
  // We'll spawn it regardless for simplicity here, assuming it handles port 8000
  console.log("Starting Python backend...");

  const isWin = process.platform === "win32";
  const pythonCmd = process.env.PYTHON_PATH || (isWin ? "python" : "python3");

  const startBackend = () => {
    const pythonProcess = spawn(
      pythonCmd,
      ["-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", String(backendPort), "--no-proxy-headers"],
      {
        cwd: path.join(process.cwd(), "backend"),
        stdio: "inherit",
        shell: false,
        windowsHide: true,
        env: { ...process.env, NODE_EXECUTABLE: process.execPath, PYTHONIOENCODING: "utf-8", FENGSHEN_DOWNLOAD_PROXY_SECRET: proxySecret },
      },
    );

    pythonProcess.on("error", (err) => {
      console.error(`Failed to start python:`, err);
    });

    pythonProcess.on("close", (code) => {
      console.log(`Python backend exited with code ${code}`);
    });

    const cleanup = () => {
      try { pythonProcess.kill(); } catch (e) {}
    };
    process.on("exit", cleanup);
    process.on("SIGINT", () => { cleanup(); server.close(); releaseStartupLock(); process.exit(0); });
    process.on("SIGTERM", () => { cleanup(); server.close(); releaseStartupLock(); process.exit(0); });
    process.on("SIGUSR1", cleanup);
    process.on("SIGUSR2", cleanup);
  };

  const runAsyncCmd = (cmd: string, args: string[]) =>
    new Promise<number>((resolve) => {
      const child = spawn(cmd, args, { stdio: "inherit", shell: false, windowsHide: true });
      child.on("error", () => resolve(1));
      child.on("close", (code) => resolve(code ?? 1));
    });

  const setupAndStartBackend = async () => {
    try {
      const checkCode = await runAsyncCmd(pythonCmd, ["-c", "import fastapi, uvicorn, pandas, polars"]);
      if (checkCode !== 0) {
        const pipCode = await runAsyncCmd(pythonCmd, ["-m", "pip", "--version"]);
        if (pipCode !== 0) {
          await runAsyncCmd(pythonCmd, ["-c", "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', '/tmp/get-pip.py')"]);
          await runAsyncCmd(pythonCmd, ["/tmp/get-pip.py", "--break-system-packages"]);
        }
        await runAsyncCmd(pythonCmd, ["-m", "pip", "install", "-r", "backend/requirements.txt", "--break-system-packages", "-q"]);
      }
      const pwCode = await runAsyncCmd(pythonCmd, ["-c", "import playwright"]);
      if (pwCode !== 0) {
        await runAsyncCmd(pythonCmd, ["-m", "pip", "install", "-r", "backend/requirements-crawler.txt", "--break-system-packages", "-q"]);
      }
    } catch (err) {
      console.error("Error setting up python env:", err);
    }
    startBackend();
  };

  if (localTestMode) {
    console.log("Local test mode: dependency installation, port cleanup and data cleanup are disabled.");
    startBackend();
  } else {
    void setupAndStartBackend();
  }

  const getWorkspaceId = (req: any) => {
    let wid = req.header("x-workspace-id");
    if (wid) {
      try { wid = decodeURIComponent(wid); } catch(e) {}
    } else {
      wid = req.query.workspace_id ? String(req.query.workspace_id) : "default";
    }
    return wid.toString().replace(/[^a-zA-Z0-9_\-\u4e00-\u9fa5]/g, "");
  };

  const isCloudEnvironment = !!process.env.K_SERVICE || !!process.env.K_REVISION || !!process.env.DISABLE_HMR;

  
  app.get("/api/chat/config", (req, res) => {
    res.json({
      groupName: "全员广场",
      welcomeMessages: [
        "操作员已成功进入系统！",
        "今日业务准备就绪，准时打卡！",
        "安全校验通过，已签到登录。",
        "各项服务状态良好，签到完毕。",
        "开启高效核算的一天！"
      ],
      logicAnswers: {"为什么团队名称修改后蓝橙无单价？":"**关于团队名称同步与匹配蓝橙单价的问题排查**\\n您好，关于此问题，系统确实已经将**“团队名称”**全面同步到了整个蓝橙单价甚至全局的匹配逻辑中。导致现在全部显示“无单价”的原因并非没同步，而是**数据本身存在字符串匹配差异**。\\n\\n* **旧版逻辑（兼容团队ID）**：之前系统对“团队”关键词抓取时没有过滤掉 `id` 字符，这就导致如果列名为“团队id”，系统会默认抓取到两个表的【团队ID】进行数值比对（例如 `123456` == `123456`），因为数字ID高度一致不会带有多余空格字眼，所以能够成功匹配出单价。\\n* **当前逻辑（强制匹配团队名称）**：为了响应您对于“日单量表直接匹配团队名称而不是团队ID”的需求，系统现已全面排除了 `id`，强制提取【团队名称】。一旦系统使用这种方式，您的“日单量表（业务明细）”中“团队名称”列的中文文本，与您存放在 `兼职价格档案` 等配置文件中填写的“团队名称”一旦存在**任何微小差异**（如包含多余空格、或者简称“南山一队”对照“南山区一站”等没有严格对齐），就会导致查无此站，触发默认价格“无”。\\n* **解决方案建议**：由于中文团队名称极其容易出现数据源填报差异（导致无法精确命中索引字典），建议您排查工资业务表和价格档案两端是否存在团队名称文本不统一或含有不可见字符的问题。如果您希望恢复此前精准的匹配体验，可以再次告知我：**“帮我把兼职和蓝橙的匹配基准回滚为团队ID”** 或者您核对一下价格表及明细表的团队名称确切保持100%中文一致来解决。","安全基金表出勤天数生成逻辑？":"**安全基金中出勤天数的计算逻辑**\\n系统中的安全基金/非蜂卡的考勤扣减依据如下：\\n\\n* **有效计算**：读取处理后的发薪详单，剔除掉标红的“欺诈单（值为0不核算）”后，统计每一位骑手在不同“账单时间”（自然日）下产生过完单的不重复天数。\\n* **合并主站点规则**：有些骑手可能会在同个月内横跨跑了多个团队站点。为了避免同一个骑手多份挂靠扣费，代码会计算他**单量最多**的那个团队作为“主站”。所有出勤天数将会全部汇总合并展示在他的主站明细下；其他辅助站点其名下的出勤天均标记为 0，以此避免对同一个骑手重复叠加扣取安全基金。\\n* **梯度天数逻辑**：由 `calc_deduction_new` 控制算法。若汇总的出勤天不足 15 天，按“（对应金额 ÷ 当月天数）× 实际出勤天数”折算出安全基金；如果出勤满 15 天及以上，则直接按满月正常天数直接扣整额。","价格档案匹配逻辑是怎样的？":"**关于价格匹配逻辑（蓝橙单价/兼职单价）**\\n目前系统的单价核心匹配逻辑是一套严格的三重主键比对机制：\\n\\n* **数据预处理：** 当系统读取「兼职价格档案」和「日单量日结表」时，会自动精准匹配抓取核心字段。\\n* **精准匹配：** 根据日期、站点、风神骑手ID等组合进行绝对匹配。","全勤出勤天数计算逻辑是什么？":"**出勤天数计算引擎**\\n核算系统同时参考两大数据源，以确保数据公正并防止作弊。","配送所得基础工资怎么算？":"**配送所得的基本核算公式**\\n系统执行的核心价值在于将庞大繁琐的运单最终转化为实际金额。生成逻辑：\\n\\n* **基础匹配公式**： `单笔配送费 = 有效完成单 × 命中单价`\\n* **有效单筛选**：在实际相乘之前，会预先剔除被标记为“取消单”、“欺诈单”的数据。只有【完成单】可以进入基数。\\n* **阶梯激励计算**：部分团队或城市如果开启了超量阶梯配置（如，月累计超过800单后，每单额外补0.5元）。处理器会统计个人的该月累计单量 `sum_orders`，当超过特定阈值段时，自动为超过的部分赋予高阶价格并差额补贴。\\n* **输出写入**：计算后的结果会通过预制的公式或者数值写入到最终工资表的 `【配送所得】` 栏位中，作为加项金额。","蓝橙单价反写到配送所得表备注中匹配逻辑是怎样的？":"**单价反写至“配送所得表”备注的逻辑规则**\\n为了能在此表中直观看到骑手该月经历的单价变动，系统会执行一套回写匹配：\\n\\n* **核心关联主键**：程序在读取到“配送所得表”时，会逐行提取当前行的 **【团队名称】** 和 **【风神骑手ID】**。\\n* **追溯历史单价**：随后使用这一对复合主键 `团队名称 + 骑手ID`，去庞大的“日单量”表底表记录字典中查找该名骑手在整个计算周期内的“每天对应的单价值”。\\n* **高级聚合与备注生成**：\\n * **单一价格：** 如果该骑手整个周期内价格自始至终没变，备注栏会被**自动清空**以保持版面整洁，并在专设的“蓝橙单价”列单独填入具体价格数字。\\n * **多重价格变动：** 当骑手被匹配到多个不同日期的有效价格时，程序会按自然日对价格进行连续性折叠聚合，将变动记录按日期回写到 `备注` 栏位（生成形如 `1日-15日单价5.5元；16日-30日单价6元` 的字符串记录）。并在“蓝橙单价”专属列打上分号分割的标记（如 `5.5;6`）。\\n * **无单价记录：** 如果该骑手在某些天份未能获取到价格（判定为无单价），系统一定会重点将其断带日期强制注入备注（如 `4日-7日无单价`），以警示复核人员。\\n\\n**总结**：配送所得表反写单价的基础是严格依赖 **团队名称 + 骑手ID**，只要这两个字段与日单量表里的该员工所属团队及ID相同，备注及价格变动记录必会成功反写。","为什么会有跨站合并的情况？":"**跨站（多团队挂靠）的数据合并初衷**\\n实际运营中，因为运力调度或兼职骑手活跃区域变动，常常引发一个骑手当月归属于多个不同网格站：\\n\\n* **唯一主键整合**：为了避免同一员工因为跑了不同的站，最终收到支离破碎的多次小额发薪或被**重复扣除安全基金卡费**。计算系统始终以 `唯一骑手身份证ID/系统ID` 作为聚合主键。\\n* **提取与汇总**：代码会自动跨所有的站点分表，提取该主键产生过的所有单量、额外津贴及扣除款项。\\n* **主从关系输出**：它将判断哪个网格站的完成单量占比最高（即“主站”），并将汇总后“一整条合并且完整的流水记录”全部归并展示在主站。辅站仅仅保留基础业务痕迹，但薪资金额标记为 `[已合并至主站]`，最终实发呈现出整齐唯一的结果。"}, quickPhrases: [
        "为什么团队名称修改后蓝橙无单价？",
        "安全基金表出勤天数生成逻辑？",
        "价格档案匹配逻辑是怎样的？",
        "出勤天数异常怎么处理？",
        "违规单和问题单怎么处理？",
        "后台数据同步有延迟吗？",
        "今天的蓝橙单价更新了吗？",
        "发现个别兼职运单核对不上。",
        "有没有最新版的操作手册？",
        "这批问题单生成耗时比昨天长。"
      ]
    });
  });

  app.get("/api/sys-info", (req, res) => {
    const ip = req.headers["x-forwarded-for"] || req.socket.remoteAddress || "127.0.0.1";
    res.json({ ip });
  });

  app.get("/api/default_paths", (req, res) => {
    let configPath = path.resolve("data/config.json");
    if (!fs.existsSync(configPath) && fs.existsSync(path.resolve("data/config.xlsx"))) {
      configPath = path.resolve("data/config.xlsx");
    }
    let dataPath = path.resolve("./uploads");

    res.json({
      configPath: configPath,
      dataPath: dataPath,
    });
  });


  app.get("/api/config", (req, res) => {
    try {
      const wid = getWorkspaceId(req);
      res.json(readWorkspaceConfig(process.cwd(), wid));
    } catch (e) {
      res.json({});
    }
  });

  app.post("/api/config", legacyJson(), (req: express.Request, res: express.Response) => {
    try {
      const wid = getWorkspaceId(req);
      writeWorkspaceConfig(process.cwd(), wid, req.body);
      res.json({ success: true });
    } catch (e) {
      res.json({ success: false, error: String(e) });
    }
  });

  app.post("/api/config_excel_data", legacyJson(), async (req: express.Request, res: express.Response) => {
    try {
      let { configPath } = req.body;
      
      // 优先使用标准配置路径 data/config.json 避免错乱
      const standardConfig = path.resolve("data/config.json");
      if (fs.existsSync(standardConfig)) {
        configPath = standardConfig;
      } else if (configPath && !fs.existsSync(configPath) && configPath.endsWith("config.xlsx")) {
        const dir = path.dirname(configPath);
        if (fs.existsSync(dir)) {
          const files = fs.readdirSync(dir);
          // 仅匹配文件名中含有 config 关键词的 JSON/Excel 文件，杜绝误拿骑手或天津商翼等业务数据文件
          const jsonFile = files.find(f => f.endsWith(".json") && f.toLowerCase().includes("config"));
          if (jsonFile) {
            configPath = path.join(dir, jsonFile);
          } else {
            const xlsxFile = files.find(f => (f.endsWith(".xlsx") || f.endsWith(".xls")) && f.toLowerCase().includes("config"));
            if (xlsxFile) {
              configPath = path.join(dir, xlsxFile);
            }
          }
        }
      }

      if (!configPath || !fs.existsSync(configPath)) {
        if (fs.existsSync(path.resolve("data/config.json"))) {
          configPath = path.resolve("data/config.json");
        } else if (fs.existsSync(path.resolve("data/config.xlsx"))) {
          configPath = path.resolve("data/config.xlsx");
        } else {
          return res.json({ success: false, error: "Config file not found", path: configPath });
        }
      }

      const cities: Record<string, any> = {};
      let totalTeams = 0;

      if (configPath.endsWith(".json")) {
        const rows = JSON.parse(fs.readFileSync(configPath, "utf-8"));
        if (!rows || rows.length === 0) {
          return res.json({ success: false, error: "empty config", data: null });
        }

        let lastCity = "";
        for (let i = 0; i < rows.length; i++) {
          const row = rows[i];
          if (!row) continue;

          let city = row["城市"] || row["city"];
          if (city) {
            lastCity = String(city).trim();
          }

          if (lastCity) {
            const cityStr = lastCity;
            const team = row["团队名称"] || row["团队"] || row["team"];
            let teamStr = team ? String(team).trim().replace(/_?新专送/g, '') : "";

            if (!cities[cityStr]) {
              cities[cityStr] = {
                total_riders: 0,
                total_orders: 0,
                fengshen_bind_rate: "0.0%",
                shangyi_bind_rate: "0.0%",
                black_count: 0,
                stations: []
              };
            }
            if (teamStr && !cities[cityStr].stations.find((s: any) => s.station_name === teamStr)) {
               cities[cityStr].stations.push({
                 station_name: teamStr,
                 total_riders: 0,
                 total_orders: 0,
                 fengshen_bind_rate: "0.0%",
                 shangyi_bind_rate: "0.0%",
                 black_count: 0
               });
               totalTeams++;
            }
          }
        }
      } else {
        const xlsx = await import("xlsx");
        const readFile = xlsx.readFile || xlsx.default.readFile;
        const workbook = readFile(configPath);
        let sheetName = "config";
        
        if (!workbook.SheetNames.includes(sheetName)) {
          sheetName = workbook.SheetNames[0]; // fallback to first sheet if "config" not found
        }

        const sheet = workbook.Sheets[sheetName];
        const utils = xlsx.utils || xlsx.default.utils;
        const data: any[][] = utils.sheet_to_json(sheet, { header: 1 });
        
        if (!data || data.length === 0) {
          console.log("Config excel is empty");
          return res.json({ success: false, error: "empty sheet", data: null });
        }

        const headerRow = data[0];
        console.log("Config headers:", headerRow);
        const cityIdx = headerRow.findIndex((col: any) => col === "城市" || String(col).includes("城"));
        const teamIdx = headerRow.findIndex((col: any) => col === "团队名称" || col === "团队" || String(col).includes("站"));

        if (cityIdx === -1 || teamIdx === -1) {
          console.log("Missing columns, cityIdx:", cityIdx, "teamIdx:", teamIdx);
          return res.json({ success: false, error: "Missing columns 城市 or 团队名称", data: null });
        }

        let lastCity = "";
        for (let i = 1; i < data.length; i++) {
          const row = data[i];
          if (!row || row.length === 0) continue;
          
          let city = row[cityIdx];
          if (city) {
            lastCity = String(city).trim();
          }
          
          if (lastCity) {
            const cityStr = lastCity;
            const team = row[teamIdx];
            let teamStr = team ? String(team).trim().replace(/_?新专送/g, '') : "";

            if (!cities[cityStr]) {
              cities[cityStr] = {
                total_riders: 0,
                total_orders: 0,
                fengshen_bind_rate: "0.0%",
                shangyi_bind_rate: "0.0%",
                black_count: 0,
                stations: []
              };
            }
            if (teamStr && !cities[cityStr].stations.find((s: any) => s.station_name === teamStr)) {
               cities[cityStr].stations.push({
                 station_name: teamStr,
                 total_riders: 0,
                 total_orders: 0,
                 fengshen_bind_rate: "0.0%",
                 shangyi_bind_rate: "0.0%",
                 black_count: 0
               });
               totalTeams++;
            }
          }
        }
      }

      const statsData = {
        overall: {
          total_riders: 0,
          total_orders: 0,
          fengshen_bind_rate: "0.0%",
          shangyi_bind_rate: "0.0%",
          black_count: 0,
          fengshen_bind_count: 0,
          shangyi_bind_count: 0
        },
        cities: cities
      };

      res.json({ success: true, data: statsData });

    } catch (e) {
      res.json({ success: false, error: String(e) });
    }
  });

  app.get("/api/field_mapping", (req, res) => {
    try {
      const wid = getWorkspaceId(req);
      const mappingFile = `.aegis_mapping_${wid}.json`;
      if (fs.existsSync(mappingFile)) {
        const data = fs.readFileSync(mappingFile, "utf-8");
        res.json(JSON.parse(data));
      } else {
        res.json({});
      }
    } catch (e) {
      res.json({});
    }
  });

  app.post("/api/field_mapping", legacyJson(), (req: express.Request, res: express.Response) => {
    try {
      const wid = getWorkspaceId(req);
      const mappingFile = `.aegis_mapping_${wid}.json`;
      fs.writeFileSync(mappingFile, JSON.stringify(req.body, null, 2), "utf-8");
      res.json({ success: true });
    } catch (e) {
      res.json({ success: false, error: String(e) });
    }
  });

  // Proxy /api to the Python backend
  // EXCEPT for upload endpoints defined above
  const storage = multer.diskStorage({
    destination: (req, file, cb) => {
      const wid = getWorkspaceId(req);
      const dir = path.join(process.cwd(), "uploads", wid);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      cb(null, dir);
    },
    filename: (req, file, cb) => {
      if (req.path === '/api/upload/source_zip') {
        cb(null, `source_upload_${randomUUID()}.zip`);
        return;
      }
      // Retain original filename, fix potential multer string encoding issue
      let decodedName = file.originalname;
      try {
        decodedName = Buffer.from(file.originalname, "latin1").toString("utf8");
      } catch (e) {}

      // Ensure unique but readable name if you want, or just overwrite the original
      cb(null, decodedName);
    },
  });
  const upload = multer({ storage });
  const sourceUpload = multer({storage, limits: {fileSize: 11 * 1024 ** 3, files: 1}});

  app.get("/api/salary_bind/download", (req, res) => {
    try {
      const month = req.query.month as string;
      if (!month) return res.status(400).send("Month is required");
      if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) return res.status(400).send("Invalid month");
      
      let absolutePath = path.resolve(process.cwd(), "outputs", "骑手支付绑定", month);
      
      if (!fs.existsSync(absolutePath)) {
        // Find it under a year folder
        const rootDir = path.resolve(process.cwd(), "outputs", "骑手支付绑定");
        if (fs.existsSync(rootDir)) {
          const years = fs.readdirSync(rootDir);
          for (const year of years) {
            const yearPath = path.join(rootDir, year);
            if (fs.statSync(yearPath).isDirectory()) {
               const potentialPath = path.join(yearPath, month);
               if (fs.existsSync(potentialPath)) {
                 absolutePath = potentialPath;
                 break;
               }
            }
          }
        }
      }

      if (!fs.existsSync(absolutePath)) {
        return res.status(404).send("Data for this month not found");
      }

      const stat = fs.statSync(absolutePath);
      if (stat.isDirectory()) {
        if (!legacyBoundary.allowedTree(absolutePath)) return legacyBoundary.reject(res);
        const zip = new AdmZip();
        zip.addLocalFolder(absolutePath);
        const zipBuffer = zip.toBuffer();
        res.set("Content-Type", "application/zip");
        res.set(
          "Content-Disposition",
          `attachment; filename="${encodeURIComponent(month + "_骑手支付绑定")}.zip"`,
        );
        res.send(zipBuffer);
      } else {
        res.status(400).send("Not a directory");
      }
    } catch (e) {
      console.error(e);
      res.status(500).send(String(e));
    }
  });

  app.get("/api/download", (req, res) => {
    try {
      res.set('Cache-Control', 'no-store');
      res.set('X-Content-Type-Options', 'nosniff');
      const qPath = req.query.path as string;
      if (!qPath) return res.status(400).send("Path is required");
      const absolutePath = path.resolve(qPath);
      if (!legacyBoundary.allowedPath(absolutePath, { recursive: true })) return legacyBoundary.reject(res);

      const wid = getWorkspaceId(req);
      const isRootConfig = absolutePath === path.resolve("data/config.json") || absolutePath === path.resolve("data/config.xlsx");

      let finalPath = absolutePath;
      if (!fs.existsSync(finalPath)) {
        if (qPath.endsWith("config.json") || qPath.endsWith("config.xlsx") || path.basename(qPath).toLowerCase().includes("config")) {
          const fb1 = path.resolve("data/config.json");
          const fb2 = path.resolve("data/config.xlsx");
          if (fs.existsSync(fb1)) finalPath = fb1;
          else if (fs.existsSync(fb2)) finalPath = fb2;
        }
      }

      if (!fs.existsSync(finalPath)) {
        return res.status(404).send("File not found");
      }

      const stat = fs.statSync(finalPath);
      if (stat.isDirectory()) {
        if (!legacyBoundary.allowedTree(finalPath)) return legacyBoundary.reject(res);
        const zip = new AdmZip();
        zip.addLocalFolder(finalPath);
        const zipBuffer = zip.toBuffer();
        const folderName = path.basename(finalPath);
        res.set("Content-Type", "application/zip");
        res.set(
          "Content-Disposition",
          `attachment; filename="result.zip"; filename*=UTF-8''${encodeURIComponent(folderName)}.zip`,
        );
        res.send(zipBuffer);
      } else {
        const fileName = path.basename(finalPath);
        res.set(
          "Content-Disposition",
          `attachment; filename="download"; filename*=UTF-8''${encodeURIComponent(fileName)}`,

        );
        res.sendFile(finalPath);
      }
    } catch (e) {
      res.status(500).send(String(e));
    }
  });

  
  app.post("/api/update_config_cities", legacyJson(), async (req: express.Request, res: express.Response) => {
    try {
      const { mapping } = req.body;
      if (!mapping || Object.keys(mapping).length === 0) {
        return res.json({ success: true });
      }
      
      const configPaths = [
        path.join(process.cwd(), "data", "config.json"),
        path.join(process.cwd(), "data", "config.xlsx"),
      ];
      let targetPath = configPaths[0];
      for (const p of configPaths) {
        if (fs.existsSync(p)) {
          targetPath = p;
          break;
        }
      }
      
      if (targetPath.endsWith(".json")) {
        let jsonData: any[] = [];
        if (fs.existsSync(targetPath)) {
          try {
            jsonData = JSON.parse(fs.readFileSync(targetPath, "utf-8"));
          } catch(e) {
            jsonData = [];
          }
        }
        
        for (const [team, city] of Object.entries(mapping)) {
          let found = false;
          for (let i = 0; i < jsonData.length; i++) {
            if (String(jsonData[i]["团队名称"]).trim() === team) {
              jsonData[i]["城市"] = city;
              found = true;
              break;
            }
          }
          if (!found) {
            const firstRow = jsonData[0] || {};
            const newRow: any = {};
            for (const key of Object.keys(firstRow)) {
              newRow[key] = (key !== "城市" && key !== "团队名称" && key !== "团队ID") ? 0 : "";
            }
            newRow["团队名称"] = team;
            newRow["城市"] = city;
            if ("团队ID" in newRow) {
              newRow["团队ID"] = "";
            }
            jsonData.push(newRow);
          }
        }
        fs.writeFileSync(targetPath, JSON.stringify(jsonData, null, 2), "utf-8");
        return res.json({ success: true });
      } else {
        let workbook;
        if (fs.existsSync(targetPath)) {
          workbook = XLSX.read(fs.readFileSync(targetPath), { type: 'buffer' });
        } else {
          workbook = XLSX.utils.book_new();
          const ws = XLSX.utils.aoa_to_sheet([["团队名称", "城市"]]);
          XLSX.utils.book_append_sheet(workbook, ws, "Sheet1");
        }
        
        const sheetName = workbook.SheetNames[0];
        const worksheet = workbook.Sheets[sheetName];
        const jsonData = XLSX.utils.sheet_to_json(worksheet, { header: 1 });
        
        if (jsonData.length === 0) {
          jsonData.push(["团队名称", "城市"]);
        }
        
        const headers = jsonData[0] as string[];
        let teamIdx = headers.findIndex(h => String(h).trim() === "团队名称");
        let cityIdx = headers.findIndex(h => String(h).trim() === "城市");
        
        if (teamIdx === -1) { teamIdx = headers.length; headers.push("团队名称"); }
        if (cityIdx === -1) { cityIdx = headers.length; headers.push("城市"); }
        
        for (const [team, city] of Object.entries(mapping)) {
          let found = false;
          for (let i = 1; i < jsonData.length; i++) {
            const row = jsonData[i] as any[];
            if (String(row[teamIdx]).trim() === team) {
              row[cityIdx] = city;
              found = true;
              break;
            }
          }
          if (!found) {
            const newRow = [];
            newRow[teamIdx] = team;
            newRow[cityIdx] = city;
            jsonData.push(newRow);
          }
        }
        
        const newWs = XLSX.utils.aoa_to_sheet(jsonData as any[][]);
        workbook.Sheets[sheetName] = newWs;
        XLSX.writeFile(workbook, targetPath, { compression: true });
        
        res.json({ success: true });
      }
    } catch (e) {
      console.error(e);
      res.status(500).json({ success: false, error: String(e) });
    }
  });
  app.post("/api/save_config", upload.single("file") as any, (req: any, res: any) => {
    try {
      if (!req.file) {
        return res
          .status(400)
          .json({ success: false, error: "No file uploaded" });
      }
      const targetPath = req.body.targetPath;
      if (targetPath && !legacyBoundary.allowedPath(targetPath, { write: true, recursive: true })) return legacyBoundary.reject(res);
      if (!targetPath) {
        return res
          .status(400)
          .json({ success: false, error: "targetPath is required" });
      }

      const wid = getWorkspaceId(req);
      const isRootConfig = targetPath === path.resolve("data/config.json") || targetPath === path.resolve("data/config.xlsx");
      if (
        !isRootConfig &&
        !targetPath.includes(`/${wid}/`) &&
        !targetPath.includes(`\\${wid}\\`)
      ) {
        return res
          .status(403)
          .json({
            success: false,
            error: "Forbidden. Path not in your workspace.",
          });
      }

      fs.copyFileSync(req.file.path, targetPath);
      res.json({ success: true, path: targetPath });
    } catch (e) {
      res.status(500).json({ success: false, error: String(e) });
    }
  });

  app.post("/api/upload/config", upload.single("file") as any, (req: any, res: any) => {
    try {
      if (!req.file) {
        return res
          .status(400)
          .json({ success: false, error: "No file uploaded" });
      }
      const absolutePath = path.resolve(req.file.path);
      res.json({ success: true, path: absolutePath });
    } catch (e) {
      res.status(500).json({ success: false, error: String(e) });
    }
  });

  app.post("/api/upload/chat_file", upload.array("files", 1000) as any, (req: any, res: any) => {
    try {
      const files = req.files as Express.Multer.File[];
      if (!files || files.length === 0) {
        return res.status(400).json({ success: false, error: "No files uploaded" });
      }
      
      const wid = getWorkspaceId(req);
      const rootOutputs = path.join(process.cwd(), "outputs");
      if (!fs.existsSync(rootOutputs)) fs.mkdirSync(rootOutputs, { recursive: true });
      
      const targetDir = path.join(rootOutputs, wid);
      if (!fs.existsSync(targetDir)) fs.mkdirSync(targetDir, { recursive: true });
      
      let paths = req.body.paths;
      if (typeof paths === "string") {
        try {
          paths = JSON.parse(paths);
        } catch(e) {}
      }
      
      if (!paths || !Array.isArray(paths)) {
         paths = files.map(f => Buffer.from(f.originalname, 'latin1').toString('utf8'));
      }
      
      const uploadedInfo: Array<{name: string, path: string, url: string}> = [];
      
      for (let i = 0; i < files.length; i++) {
         const file = files[i];
         const relativePath = paths[i] || Buffer.from(file.originalname, 'latin1').toString('utf8');
         const targetPath = path.resolve(targetDir, relativePath);
         const within = path.relative(targetDir, targetPath);
         if (within === ".." || within.startsWith(".." + path.sep) || path.isAbsolute(within) ||
             !legacyBoundary.allowedPath(targetPath, { write: true })) return legacyBoundary.reject(res);
         
         const dir = path.dirname(targetPath);
         if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
         
         fs.copyFileSync(file.path, targetPath);
         uploadedInfo.push({
           name: relativePath,
           path: targetPath,
           url: `/api/download?path=${encodeURIComponent(targetPath)}`
         });
      }
      
      res.json({ success: true, files: uploadedInfo });
    } catch (e) {
      res.status(500).json({ success: false, error: String(e) });
    }
  });

  app.post(
    "/api/upload/source_zip",
    (req: any, res: any, next: any) => sourceUpload.single('file')(req, res, (error: any) => {
      if (error) return res.status(error.code === 'LIMIT_FILE_SIZE' ? 413 : 400).json({success: false,
        error: error.code === 'LIMIT_FILE_SIZE' ? '上传文件包超过11GiB传输限制（资料解压后单批最多10GiB）' : '上传请求无效，请一次选择一批资料'});
      next();
    }),
    async (req: any, res: any) => {
      const processingStarted = performance.now();
      try {
        if (!req.file) {
          return res
            .status(400)
            .json({ success: false, error: "No file uploaded" });
        }
        const wid = getWorkspaceId(req);
        const zipPath = req.file.path;
        // Also save data in wid specific folder
        const targetDir = path.join(
          process.cwd(),
          "uploads",
          wid,
          `upload_${getUploadSequence(wid)}_${randomUUID().slice(0, 8)}`,
        );
        fs.mkdirSync(targetDir, { recursive: true });

        const extractionStarted = performance.now();
        await extractSourceArchive(pythonCmd, process.cwd(), zipPath, targetDir);
        const extractionSeconds = (performance.now() - extractionStarted) / 1000;
        const indexingStarted = performance.now();

        // Cleanup zip：清理失败不影响已解压挂载的数据，降级为告警（非致命）
        try {
          fs.unlinkSync(zipPath);
        } catch (cleanupErr) {
          console.warn(
            "[source_zip] 临时 zip 清理失败（不影响本次上传）:",
            cleanupErr,
          );
        }

        let finalPath = targetDir;
        let items = fs.readdirSync(finalPath);
        
        // If there's exactly one item and it's a directory, unwrap it (skip the wrapper folder from zip)
        if (items.length === 1) {
          const firstItemPath = path.join(finalPath, items[0]);
          if (fs.statSync(firstItemPath).isDirectory()) {
             finalPath = firstItemPath;
             items = fs.readdirSync(finalPath);
          }
        }

        const absolutePath = path.resolve(finalPath);

        const findTemplates = (dir: string): { relativePath: string; absolutePath: string }[] => {
          let results: { relativePath: string; absolutePath: string }[] = [];
          try {
            const list = fs.readdirSync(dir);
            for (const file of list) {
              const fullPath = path.join(dir, file);
              const stat = fs.statSync(fullPath);
              if (stat.isDirectory()) {
                if (!file.startsWith('__') && !file.startsWith('.')) {
                  results = results.concat(findTemplates(fullPath));
                }
              } else {
                const lower = file.toLowerCase();
                if (lower.includes("template") && (lower.endsWith(".xlsx") || lower.endsWith(".xls")) && !file.startsWith("~$") && !file.startsWith(".")) {
                  results.push({
                    relativePath: path.relative(finalPath, fullPath),
                    absolutePath: fullPath
                  });
                }
              }
            }
          } catch (e) {
            console.error("Error in findTemplates:", e);
          }
          return results;
        };

        const templateFiles = findTemplates(finalPath);
        
        let tasks: any[] = [];
        if (templateFiles.length > 0) {
          tasks = templateFiles.map(template => {
            const templatePath = template.absolutePath;
            const taskDir = path.dirname(templatePath);
            const templateFilename = path.basename(templatePath);
            
            let fileCount = 0;
            let totalSize = 0;
            const isSalaryBind = false;

            const computeStats = (dir: string) => {
              const files = fs.readdirSync(dir);
              for (const f of files) {
                const fullPath = path.join(dir, f);
                const stat = fs.statSync(fullPath);
                if (stat.isDirectory()) {
                  // Don't recursively count other subdirs if they are separate subtasks, but let's count helper dirs
                  if (!f.startsWith('__') && !f.startsWith('.')) {
                    computeStats(fullPath);
                  }
                } else {
                  fileCount++;
                  totalSize += stat.size;
                }
              }
            };
            try {
              computeStats(taskDir);
            } catch (err) {
              console.error("Error scanning task folder stats:", err);
            }

            let cityName = '';
            try {
              const workbook = XLSX.read(fs.readFileSync(templatePath), { type: 'buffer' });
              const sheetName = workbook.SheetNames.find(n => n.includes("申请名单"));
              if (sheetName) {
                const worksheet = workbook.Sheets[sheetName];
                const jsonData = XLSX.utils.sheet_to_json(worksheet, { header: 1 });
                if (jsonData && jsonData.length > 0) {
                  let cityColIdx = -1;
                  const headers: any = jsonData[0];
                  if (Array.isArray(headers)) {
                    cityColIdx = headers.findIndex((h: any) => String(h).includes("城市"));
                  }
                  if (cityColIdx === -1) {
                    for (let r = 0; r < Math.min(10, jsonData.length); r++) {
                      const row: any = jsonData[r];
                      if (Array.isArray(row)) {
                        const idx = row.findIndex((h: any) => String(h).includes("城市"));
                        if (idx !== -1) {
                          cityColIdx = idx;
                          break;
                        }
                      }
                    }
                  }
                  if (cityColIdx !== -1) {
                    for (let r = 1; r < jsonData.length; r++) {
                      const row: any = jsonData[r];
                      if (Array.isArray(row) && row[cityColIdx]) {
                        const val = String(row[cityColIdx]).trim();
                        if (val && val.toLowerCase() !== 'nan' && val.toLowerCase() !== 'none') {
                          cityName = val;
                          break;
                        }
                      }
                    }
                  }
                }
              }
            } catch (err) {
              console.error("Error reading business city from template:", err);
            }

            let displayName = cityName || path.basename(taskDir) || "未知城市";
            const filenameNoExt = path.basename(templateFilename, path.extname(templateFilename));
            if (filenameNoExt !== "template" && filenameNoExt !== "兼职-template") {
              let suffix = filenameNoExt;
              if (suffix.startsWith("兼职-template")) {
                suffix = suffix.substring("兼职-template".length);
              } else if (suffix.toLowerCase().includes("template")) {
                suffix = suffix.replace(/template/i, '');
              }
              suffix = suffix.replace(/^[-_]/, '').replace(/[-_]$/, '');
              if (suffix) {
                displayName = `${displayName} (${suffix})`;
              }
            }

            return { id: template.relativePath, name: displayName, fileCount, totalSize, isSalaryBind };
          });
        } else {
          const subdirs = items.filter(f => fs.statSync(path.join(finalPath, f)).isDirectory() && !f.startsWith('__'));
          if (subdirs.length > 0) {
            tasks = subdirs.map(name => {
              const subdirPath = path.join(finalPath, name);
              let fileCount = 0;
              let totalSize = 0;
              let isSalaryBind = false;

              const computeStats = (dir: string) => {
                const files = fs.readdirSync(dir);
                for (const f of files) {
                  const fullPath = path.join(dir, f);
                  const stat = fs.statSync(fullPath);
                  if (stat.isDirectory()) {
                    computeStats(fullPath);
                  } else {
                    fileCount++;
                    totalSize += stat.size;

                    const lowerF = f.toLowerCase();
                    if (
                      lowerF.includes("绑定") ||
                      lowerF.includes("salary_bind") ||
                      lowerF.includes("发薪工具") ||
                      lowerF.includes("收薪账户") ||
                      lowerF.includes("骑手绑定") ||
                      lowerF.includes("merchantfreelancer") ||
                      lowerF.includes("天津商翼") ||
                      lowerF.includes("薪资代领") ||
                      lowerF.includes("基本资料") ||
                      lowerF.includes("rider_bind") ||
                      lowerF.includes("fengshen") ||
                      lowerF.includes("shangyi") ||
                      lowerF.includes("骑手信息") ||
                      lowerF.includes("骑手数据明细")
                    ) {
                      isSalaryBind = true;
                    }
                  }
                }
              };
              try {
                computeStats(subdirPath);
              } catch (err) {
                console.error("Error scanning subdirectory stats:", err);
              }

              const lowerName = name.toLowerCase();
              if (
                lowerName.includes("绑定") ||
                lowerName.includes("salary_bind") ||
                lowerName.includes("发薪工具") ||
                lowerName.includes("rider_bind")
              ) {
                isSalaryBind = true;
              }

              let cityName = '';
              try {
                const filesInSubdir = fs.readdirSync(subdirPath);
                const templateFile = filesInSubdir.find(f => f.toLowerCase().includes("template") && (f.endsWith(".xlsx") || f.endsWith(".xls")) && !f.startsWith("~$") && !f.startsWith("."));
                if (templateFile) {
                  const templatePath = path.join(subdirPath, templateFile);
                  const workbook = XLSX.read(fs.readFileSync(templatePath), { type: 'buffer' });
                  const sheetName = workbook.SheetNames.find(n => n.includes("申请名单"));
                  if (sheetName) {
                    const worksheet = workbook.Sheets[sheetName];
                    const jsonData = XLSX.utils.sheet_to_json(worksheet, { header: 1 });
                    if (jsonData && jsonData.length > 0) {
                      let cityColIdx = -1;
                      const headers: any = jsonData[0];
                      if (Array.isArray(headers)) {
                        cityColIdx = headers.findIndex((h: any) => String(h).includes("城市"));
                      }
                      if (cityColIdx === -1) {
                        for (let r = 0; r < Math.min(10, jsonData.length); r++) {
                          const row: any = jsonData[r];
                          if (Array.isArray(row)) {
                            const idx = row.findIndex((h: any) => String(h).includes("城市"));
                            if (idx !== -1) {
                              cityColIdx = idx;
                              break;
                            }
                          }
                        }
                      }
                      if (cityColIdx !== -1) {
                        for (let r = 1; r < jsonData.length; r++) {
                          const row: any = jsonData[r];
                          if (Array.isArray(row) && row[cityColIdx]) {
                            const val = String(row[cityColIdx]).trim();
                            if (val && val.toLowerCase() !== 'nan' && val.toLowerCase() !== 'none') {
                              cityName = val;
                              break;
                            }
                          }
                        }
                      }
                    }
                  }
                }
              } catch (err) {
                console.error("Error reading business city from template:", err);
              }

              return { id: name, name: cityName || name, fileCount, totalSize, isSalaryBind };
            });
          }
        }

        const timings = { server_seconds: (performance.now() - processingStarted) / 1000,
          extraction_seconds: extractionSeconds, indexing_seconds: (performance.now() - indexingStarted) / 1000 };
        try { fs.writeFileSync(path.join(absolutePath, '.upload_diagnostics.json'), JSON.stringify(timings), 'utf8'); } catch { /* Diagnostics are best effort. */ }
        res.json({ success: true, path: absolutePath, smart: true, tasks, timings });
      } catch (e) {
        res.status(400).json({ success: false, error: e instanceof Error ? e.message : String(e) });
      }
    },
  );

  app.post("/api/files", legacyJson(), (req: express.Request, res: express.Response) => {
    try {
      const qPath = req.body.path;
      if (!qPath) {
        return res.json({ files: [] });
      }
      
      // Auto-create predefined default external directories if they don't exist
      if ((qPath === './outputs' || qPath === './uploads') && !fs.existsSync(qPath)) {
        fs.mkdirSync(qPath, { recursive: true });
      }
      if (qPath === './outputs' || qPath === 'outputs') {
        const folders = ["问题单生成", "兼职薪资", "兼职已发汇总", "骑手支付绑定", "异常名单整理"];
        for (const f of folders) {
          const folderPath = path.join(qPath, f);
          if (!fs.existsSync(folderPath)) {
            fs.mkdirSync(folderPath, { recursive: true });
          }
        }
      }

      if (!fs.existsSync(qPath)) {
        return res.json({ files: [] });
      }
      const stat = fs.statSync(qPath);
      let targetPath = qPath;
      if (!stat.isDirectory()) {
         targetPath = path.dirname(qPath);
      }
      
      const items = fs.readdirSync(targetPath).filter(f => !f.startsWith(".") && !f.startsWith("~") &&
        legacyBoundary.allowedPath(path.join(targetPath, f))).map(f => {
         const fPath = path.join(targetPath, f);
         let isDir = false;
         let size = 0;
         let mtime = 0;
         try {
            const fStat = fs.statSync(fPath);
            isDir = fStat.isDirectory();
            size = isDir ? 0 : fStat.size;
            mtime = fStat.mtime.getTime();
         } catch(e) {}
         return { name: f, path: fPath, is_dir: isDir, size, mtime };
      });
      items.sort((a,b) => {
         if (a.is_dir === b.is_dir) return b.mtime - a.mtime; // Sort by newest first
         return a.is_dir ? -1 : 1;
      });
      res.json({ files: items });
    } catch(e) {
      res.json({ files: [] });
    }
  });

  app.post(
    "/api/v1/adjustments/batch-process",
    (multer({ storage: multer.memoryStorage() }).single("file") as any),
    async (req: any, res: any) => {
      try {
        if (!req.file) {
          return res.status(400).json({ success: false, error: "No file uploaded" });
        }
        
        // Assemble FormData
        const formData = new FormData();
        formData.append("file", req.file.buffer, {
          filename: req.file.originalname,
          contentType: req.file.mimetype,
        });

        // Pass through to FastAPI backend
        const response = await axios.post(
          `${backendUrl}/api/v1/adjustments/batch-process`,
          formData,
          {
            headers: formData.getHeaders(),
            responseType: "stream",
          }
        );

        // Pipe the response back to the client
        res.set(response.headers);
        response.data.pipe(res);
      } catch (err: any) {
        if (err.response && err.response.data) {
          err.response.data.pipe(res.status(err.response.status));
        } else {
          res.status(500).json({ success: false, error: String(err) });
        }
      }
    }
  );

  app.post("/api/action_file", legacyJson(), (req: express.Request, res: express.Response) => {
    try {
      const { action, path: targetPath } = req.body;
      if (!targetPath) return res.json({ success: false, error: 'No path' });
      
      if (action === 'delete') {
        if (fs.existsSync(targetPath)) {
          const stat = fs.statSync(targetPath);
          if (stat.isDirectory()) {
            fs.rmSync(targetPath, { recursive: true, force: true });
          } else {
            fs.unlinkSync(targetPath);
          }
        }
        res.json({ success: true });
      } else if (action === 'create_dir') {
        if (!fs.existsSync(targetPath)) {
          fs.mkdirSync(targetPath, { recursive: true });
        }
        res.json({ success: true });
      } else {
        res.json({ success: false, error: 'Unknown action' });
      }
    } catch(e) {
      res.json({ success: false, error: String(e) });
    }
  });

  app.post("/api/upload_file", upload.single("file") as any, (req: any, res: any) => {
    try {
      if (!req.file) {
        return res.status(400).json({ success: false, error: "No file uploaded" });
      }
      const targetPath = req.body.targetPath;
      if (targetPath && !legacyBoundary.allowedPath(targetPath, { write: true, recursive: true })) return legacyBoundary.reject(res);
      if (!targetPath) {
        return res.status(400).json({ success: false, error: "targetPath is required" });
      }
      const dir = path.dirname(targetPath);
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      fs.copyFileSync(req.file.path, targetPath);
      res.json({ success: true, path: targetPath });
    } catch(err) {
      res.status(500).json({ success: false, error: String(err) });
    }
  });

  app.get("/api/system/stats", async (req, res) => {
    const cpus = os.cpus();
    let totalUser = 0;
    let totalSys = 0;
    let totalIdle = 0;
    if (cpus && cpus.length > 0) {
      for (let cpu of cpus) {
        totalUser += cpu.times.user;
        totalSys += cpu.times.sys;
        totalIdle += cpu.times.idle;
      }
    }
    const totalTime = totalUser + totalSys + totalIdle;
    const sysCpu = totalTime > 0 ? ((totalUser + totalSys) / totalTime) * 100 : 0;
    const sysMemRatio = ((os.totalmem() - os.freemem()) / os.totalmem()) * 100;
    const procMem = process.memoryUsage().rss / (1024 * 1024);
    
    res.json({
      success: true,
      sysCpu: sysCpu,
      sysMemRatio: sysMemRatio,
      procCpu: 0,
      procMem: procMem
    });
  });

  // Mock endpoints for local python features that don't work in web
  app.post("/api/dialog/folder", (req, res) => {
    res.status(400).json({ success: false, error: "Not supported in web mode", path: "" });
  });

  app.post("/api/dialog/file", (req, res) => {
    res.status(400).json({ success: false, error: "Not supported in web mode", path: "" });
  });

  app.post("/api/open/config", (req, res) => {
    res.status(400).json({ success: false, error: "Not supported in web mode" });
  });

  app.post("/api/open/explorer", (req, res) => {
    res.status(400).json({ success: false, error: "Not supported in web mode" });
  });

  const proxyOptions: any = {
    target: backendUrl,
    changeOrigin: true,
    ws: true,
    on: {
      error: (err: any, req: any, res: any) => {
        if (res && typeof res.status === "function") {
          res
            .status(502)
            .json({
              success: false,
              error: "Backend starting up or unavailable.",
            });
        } else if (res && typeof res.writeHead === "function" && !res.headersSent) {
          res.writeHead(502, { "Content-Type": "application/json" });
          res.end(JSON.stringify({ success: false, error: "Backend starting up or unavailable." }));
        }
      },
    },
  };

  // Login validates the browser Origin against Host, including LAN access.
  // Preserve that Host only for these routes; other APIs keep their existing proxy behavior.
  // Match decoded routes too, so encoded auth paths cannot fall through to
  // the generic proxy and be mistaken for loopback requests by the backend.
  app.use(createDownloadProxy(proxyOptions, proxySecret));
  app.use(createFengshenAuthProxy(proxyOptions, proxySecret));
  app.use(createProxyMiddleware({ pathFilter: "/api", ...proxyOptions }));

  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: {
        middlewareMode: true,
        ...(localTestMode ? { host: listenHost, hmr: { host: listenHost } } : {}),
      },
      appType: "spa",
    });
    app.use(vite.middlewares);
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.use((req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
  }

  // Business inputs, configuration and output evidence have no age-based expiry.
  // Offline verified snapshots are managed by scripts/business_backup.py.
  console.log("Business data is retained; automatic business-directory cleanup is disabled.");


  {
    console.log(`Server is running! You can access it on:`);
    console.log(`  http://localhost:${PORT}`);

    // Print all local IP addresses
    let os;
    try {
      os = await import("os");
    } catch (e) {}
    if (os && !localTestMode) {
      const interfaces = os.networkInterfaces();
      for (const devName in interfaces) {
        const iface = interfaces[devName];
        if (iface) {
          for (let i = 0; i < iface.length; i++) {
            const alias = iface[i];
            if (
              alias.family === "IPv4" &&
              alias.address !== "127.0.0.1" &&
              !alias.internal
            ) {
              console.log(
                `  http://${alias.address}:${PORT} (For colleagues on the same network)`,
              );
            }
          }
        }
      }
    }
  }

  const io = new SocketIOServer(server, { cors: { origin: "*" } });

  const chatHistory = new Map();

  io.on("connection", (socket) => {
    socket.on("join", async (data) => {
      const { workspaceId, username, profile } = data;

      // ID limit constraint Check
      let safeUsername = (username || "匿名用户").substring(0, 15);

      socket.join(workspaceId);
      socket.data.workspaceId = workspaceId;
      socket.data.username = safeUsername;
      socket.data.profile = profile;

      let ip =
        socket.handshake.headers["x-forwarded-for"] ||
        socket.handshake.address ||
        "未知 IP";
      if (Array.isArray(ip)) ip = ip[0];
      if (typeof ip === "string") ip = ip.split(",")[0].trim();
      // basic anonymize for safety/style if desired, or keep raw.
      socket.data.ip = ip;

      if (!chatHistory.has(workspaceId)) {
        chatHistory.set(workspaceId, []);
      }
      socket.emit("history", chatHistory.get(workspaceId));

      const sendPresence = async () => {
        const sockets = await io.in(workspaceId).fetchSockets();
        const existingSockets = sockets.filter(
          (s) => s.data.username === safeUsername && s.id !== socket.id,
        );

        if (existingSockets.length === 0) {
          io.to(workspaceId).emit("user_online", { username: safeUsername });
        }

        const userMap = new Map();
        sockets.forEach((s) => {
          if (s.data.username && !userMap.has(s.data.username)) {
            userMap.set(s.data.username, {
              username: s.data.username,
              ip: s.data.ip,
              socketId: s.id,
              profile: s.data.profile,
              status: s.data.profile?.status || "在线",
            });
          }
        });
        io.to(workspaceId).emit("presence", Array.from(userMap.values()));
      };
      sendPresence();
    });

    socket.on("message", async (data) => {
      const { workspaceId, username, text, imageUrl, fileUrl, fileName, profile } = data;

      let safeUsername = (username || "匿名用户").substring(0, 15);
      let ip =
        socket.handshake.headers["x-forwarded-for"] ||
        socket.handshake.address ||
        "未知 IP";
      if (Array.isArray(ip)) ip = ip[0];
      if (typeof ip === "string") ip = ip.split(",")[0].trim();

      const msg = {
        id: Date.now().toString() + Math.random().toString(36).substring(2, 9), fromId: socket.id,
        username: safeUsername,
        profile: profile,
        text: text ? text.substring(0, 1000) : "",
        imageUrl: imageUrl || null,
        fileUrl: fileUrl || null,
        fileName: fileName || null,
        ip: ip,
        timestamp: new Date().toISOString(),
      };
      
      if (!chatHistory.has(workspaceId)) {
        chatHistory.set(workspaceId, []);
      }
      chatHistory.get(workspaceId).push(msg);
      if (chatHistory.get(workspaceId).length > 200) {
        chatHistory.get(workspaceId).shift();
      }

      io.to(workspaceId).emit("message", msg);
    });

    socket.on("clear", () => {
      // no-op on server since users clear their own locally now
    });

    socket.on("update_profile", async (profile) => {
      socket.data.profile = profile;
      const workspaceId = socket.data.workspaceId;
      if (!workspaceId) return;
      const sockets = await io.in(workspaceId).fetchSockets();
      const userMap = new Map();
      sockets.forEach((s) => {
        if (s.data.username && !userMap.has(s.data.username)) {
          userMap.set(s.data.username, {
            username: s.data.username,
            ip: s.data.ip,
            socketId: s.id,
            profile: s.data.profile,
            status: s.data.profile?.status || "在线",
          });
        }
      });
      io.to(workspaceId).emit("presence", Array.from(userMap.values()));
    });

    socket.on("private_message", (data) => {
      const { toId, text, imageUrl, fileUrl, fileName, profile } = data;
      const username = socket.data.username;

      let safeUsername = (username || "无名小妖").substring(0, 15);
      let ip =
        socket.handshake.headers["x-forwarded-for"] ||
        socket.handshake.address ||
        "未知 IP";
      if (Array.isArray(ip)) ip = ip[0];
      if (typeof ip === "string") ip = ip.split(",")[0].trim();

      // Send to the recipient
      if (toId) { const msgId = Date.now().toString() + Math.random().toString(36).substring(2, 9);
        io.to(toId).emit("private_message", {
          id: msgId, username: safeUsername,
          text: text ? text.substring(0, 1000) : "",
          imageUrl: imageUrl || null,
          fileUrl: fileUrl || null,
          fileName: fileName || null,
          profile: profile || socket.data.profile || null,
          ip: ip,
          fromId: socket.id,
          timestamp: new Date().toISOString(),
          toId: toId,
          isRead: toId === socket.id
        });
        if (toId !== socket.id) { // Also send back to sender so they see it in their UI
        socket.emit("private_message", {
          id: msgId, username: safeUsername,
          text: text ? text.substring(0, 1000) : "",
          imageUrl: imageUrl || null,
          fileUrl: fileUrl || null,
          fileName: fileName || null,
          profile: profile || socket.data.profile || null,
          ip: ip,
          fromId: socket.id,
          timestamp: new Date().toISOString(),
          isSelf: true,
          toId: toId,
        });
        }
      }
    });

    socket.on("read_receipt", (data) => {
      const { messageId, senderId } = data;
      if (senderId) {
        io.to(senderId).emit("message_read", {
          messageId,
          readerId: socket.id,
        });
      }
    });

    socket.on("typing", (data) => {
      const { workspaceId, isTyping, toId } = data;
      const username = socket.data.username || "无名小妖";
      const safeUsername = username.substring(0, 15);

      if (toId) { const msgId = Date.now().toString() + Math.random().toString(36).substring(2, 9);
        io.to(toId).emit("typing", { username: safeUsername, isTyping });
      } else {
        socket
          .to(workspaceId)
          .emit("typing", { username: safeUsername, isTyping });
      }
    });

    socket.on("nudge", (data) => {
      const { workspaceId, toId, targetName } = data;
      const username = socket.data.username || "匿名用户";
      const nudgeMsg = {
        id: Date.now().toString() + Math.random().toString(36).substring(2, 9),
        fromId: socket.id,
        username,
        profile: socket.data.profile,
        text: toId ? `👈 戳了戳 **${targetName || "你"}**` : `👈 戳了戳 **所有人**`,
        type: "system",
        timestamp: new Date().toISOString(),
        isNudge: true,
        toId
      };
      if (toId) {
        io.to(toId).emit("private_message", nudgeMsg);
        if (toId !== socket.id) socket.emit("private_message", { ...nudgeMsg, isSelf: true });
      } else {
        io.to(workspaceId).emit("message", nudgeMsg);
      }
    });

    socket.on("shake_window", (data) => {
      const { workspaceId, toId } = data;
      const username = socket.data.username || "匿名用户";
      const shakeMsg = {
        id: Date.now().toString() + Math.random().toString(36).substring(2, 9),
        fromId: socket.id,
        username,
        profile: socket.data.profile,
        text: `💥 发起了一次 **窗口抖动**！`,
        type: "system",
        timestamp: new Date().toISOString(),
        isShake: true,
        toId
      };
      if (toId) {
        io.to(toId).emit("shake_window", shakeMsg);
        io.to(toId).emit("private_message", shakeMsg);
        if (toId !== socket.id) socket.emit("private_message", { ...shakeMsg, isSelf: true });
      } else {
        io.to(workspaceId).emit("shake_window", shakeMsg);
        io.to(workspaceId).emit("message", shakeMsg);
      }
    });

    socket.on("disconnect", async () => {
      const workspaceId = socket.data.workspaceId;
      const username = socket.data.username;

      if (workspaceId) {
        try {
          const sockets = await io.in(workspaceId).fetchSockets();
          const remaining = sockets.filter((s) => s.data.username === username);

          if (username && remaining.length === 0) {
            io.to(workspaceId).emit("user_offline", { username });
          }

          const userMap = new Map();
          sockets.forEach((s) => {
            if (s.data.username && !userMap.has(s.data.username)) {
              userMap.set(s.data.username, {
                username: s.data.username,
                ip: s.data.ip,
                socketId: s.id,
                status: "online",
              });
            }
          });
          io.to(workspaceId).emit("presence", Array.from(userMap.values()));
        } catch (e) {}
      }
    });
  });
}

startServer().catch(error => {
  console.error("服务未能启动：", error instanceof Error ? error.message : "请检查启动配置");
  process.exit(1);
});
