/**
 * 应用级字面量常量（全站唯一来源）。
 *
 * 约束：本文件只能出现常量，不得引入任何依赖，不得包含 DOM 逻辑，
 * 以便被 `index.html` 口径、`App.tsx`、文档三处同时引用而不产生循环依赖。
 */

/** 应用标题：浏览器标签页、OG 标题、文档口径三者共用同一字面量。 */
export const APP_TITLE = '兼职运力与薪资结算调度中心';

/** 应用简介：`meta[name=description]` 与 `og:description` 共用。 */
export const APP_DESCRIPTION = '兼职运力采集、薪资核算与价格审批一体化调度工作台';

/** 侧栏品牌主标题。 */
export const SIDEBAR_BRAND = '薪酬结算中心';

/** 侧栏品牌副标题：宽屏展开时显示，窄栏折叠时作为 `title` 悬浮提示。 */
export const SIDEBAR_BRAND_HINT = '多平台数据采集自动化核算';
