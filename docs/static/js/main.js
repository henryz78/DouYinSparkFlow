const { createApp, ref, reactive, computed } = Vue;
const app = createApp({
  setup() {
    const message = ref("Hello vue!");

    const log_level_options = [
      {
        id: "Debug",
        label: "Debug",
        value: "Debug",
      },
      {
        id: "Info",
        label: "Info",
        value: "Info",
      },
      {
        id: "Warning",
        label: "Warning",
        value: "Warning",
      },
      {
        id: "Error",
        label: "Error",
        value: "Error",
      },
    ];

    // do not use same name with ref
    const form = reactive({
      PROXY_ADDRESS: "",
      RUN_TIME: "09:00:00",
      CRON_RANDOM_WINDOW_SECONDS: 0,
      TZ: "Asia/Shanghai",
      DELIVERY_MODE: "text",
      NATIVE_STICKER_NAME: "续火花",
      MESSAGE_TEMPLATE:
        "[盖瑞]今日火花[加一]\n—— [右边] 每日一言 [左边] ——\n[API]",
      HITOKOTO_TYPES: ["文学", "影视", "诗词", "哲学"],
      BROWSER_ACTION_TIMEOUT: 120,
      IM_SCAN_TIMEOUT: 120,
      IM_READY_TIMEOUT: 120,
      FRIEND_LIST_WAIT_TIME: 3,
      IM_MAX_STEPS: 200,
      TASK_RETRY_TIMES: 3,
      LOG_LEVEL: "Debug",
      TELEGRAM_ENABLED: false,
      TELEGRAM_BOT_TOKEN: "",
      TELEGRAM_CHAT_ID: "",
      TELEGRAM_NOTIFY_SUCCESS: true,
      TELEGRAM_NOTIFY_FAILURE: true,
      ACCOUNTS: [
        {
          username: "user1",
          unique_id: "12345678905",
          cookies:
            '[{"name":"sessionid","value":"your-sessionid","domain":".douyin.com","path":"/"},{"name":"ttwid","value":"your-ttwid","domain":".douyin.com","path":"/"}]',
          targets: ["friend1", "friend2"],
        },
      ],
    });

    const environmentVariables = computed(() => {
      const [CRON_HOUR, CRON_MINUTE, CRON_SECOND] = form.RUN_TIME.split(":");

      return {
        PROXY_ADDRESS: form.PROXY_ADDRESS,
        CRON_HOUR,
        CRON_MINUTE,
        CRON_SECOND,
        CRON_RANDOM_WINDOW_SECONDS: form.CRON_RANDOM_WINDOW_SECONDS,
        TZ: form.TZ,
        DELIVERY_MODE: form.DELIVERY_MODE,
        NATIVE_STICKER_NAME: form.NATIVE_STICKER_NAME,
        MESSAGE_TEMPLATE: form.MESSAGE_TEMPLATE,
        HITOKOTO_TYPES: form.HITOKOTO_TYPES,
        BROWSER_ACTION_TIMEOUT: form.BROWSER_ACTION_TIMEOUT,
        IM_SCAN_TIMEOUT: form.IM_SCAN_TIMEOUT,
        IM_READY_TIMEOUT: form.IM_READY_TIMEOUT,
        FRIEND_LIST_WAIT_TIME: form.FRIEND_LIST_WAIT_TIME,
        IM_MAX_STEPS: form.IM_MAX_STEPS,
        TASK_RETRY_TIMES: form.TASK_RETRY_TIMES,
        LOG_LEVEL: form.LOG_LEVEL,
        // 布尔值转成字符串：复制逻辑只处理 object / number / string
        TELEGRAM_ENABLED: String(form.TELEGRAM_ENABLED),
        TELEGRAM_BOT_TOKEN: form.TELEGRAM_BOT_TOKEN,
        TELEGRAM_CHAT_ID: form.TELEGRAM_CHAT_ID,
        TELEGRAM_NOTIFY_SUCCESS: String(form.TELEGRAM_NOTIFY_SUCCESS),
        TELEGRAM_NOTIFY_FAILURE: String(form.TELEGRAM_NOTIFY_FAILURE),
        TASKS: form.ACCOUNTS.map((account) => ({
          username: account.username,
          unique_id: account.unique_id,
          targets: account.targets,
        })),
      };
    });

    const environmentSecrets = computed(() => {
      return form.ACCOUNTS.reduce((acc, account, index) => {
        acc[`COOKIES_${String(account.unique_id || "").toUpperCase()}`] = account.cookies;
        return acc;
      }, {});
    });

    const copyValue = (value) => {
      if (typeof value === "object") {
        value = JSON.stringify(value);
      } else if (typeof value === "number") {
        value = value.toString();
      } else {
        value = value.replace(/\n/g, "\\n");
      }
      navigator.clipboard.writeText(value).then(
        () => {
          ElementPlus.ElMessage.success("已复制到剪贴板");
        },
        (err) => {
          ElementPlus.ElMessage.error("复制失败: " + err);
        }
      );
    };

    const copyEnvFile = () => {
      // 合并两个对象
      const allVars = {
        ...environmentVariables.value,
        ...environmentSecrets.value,
      };
      // 生成 .env 格式字符串
      const item = Object.entries(allVars)
        .map(([key, value]) => {
          if (typeof value === "object") {
            value = JSON.stringify(value);
          } else if (typeof value === "number") {
            value = value.toString();
          } else {
            value = value.replace(/\n/g, "\\n");
          }
          return `${key}=${value}`;
        })
        .join("\n");
      navigator.clipboard.writeText(item).then(
        () => {
          ElementPlus.ElMessage.success("已复制 .env 配置文件到剪贴板");
        },
        (err) => {
          ElementPlus.ElMessage.error("复制失败: " + err);
        }
      );
    };

    const openEnvDetails = (name, value) => {
      console.log(
        "openEnvDetails called with name:",
        name,
        "value:",
        value,
        typeof value
      );
      if (typeof value === "object") {
        value = JSON.stringify(value, null, 2);
        console.log("value is object, stringify it:", value);
      }

      ElementPlus.ElMessageBox.alert(
        "<div style='text-align: left; white-space: pre-wrap; word-break: break-all; width: 400px; max-height: 200px; overflow: auto;'>" +
          value +
          "</div>",
        `${name} 详情`,
        {
          dangerouslyUseHTMLString: true,
        }
      );
    };

    const addAccount = () => {
      form.ACCOUNTS.push({
        username: "",
        unique_id: "",
        cookies:
          '[{"name":"sessionid","value":"your-sessionid","domain":".douyin.com","path":"/"}]',
        targets: [],
      });
    };

    const removeAccount = (index) => {
      form.ACCOUNTS.splice(index, 1);
    };

    return {
      log_level_options,
      message,
      form,
      environmentVariables,
      environmentSecrets,
      copyValue,
      copyEnvFile,
      openEnvDetails,
      addAccount,
      removeAccount,
    };
  },
});
app.use(ElementPlus);
app.mount("#app");
