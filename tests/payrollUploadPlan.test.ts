import assert from "node:assert/strict";
import test from "node:test";
import { planPayrollUpload } from "../src/lib/payrollUploadPlan";

const entry = (name: string, relativePath = name) => ({ file: { name }, relativePath });

test("template files upload as automatic batches and keep multiple templates", () => {
  const groups = planPayrollUpload([
    entry("深圳-template.xlsx"),
    entry("广州-template.xlsx"),
  ]);
  assert.deepEqual(groups.map(group => group.mode), ["fengshen"]);
  assert.deepEqual(groups[0].files.map(file => file.relativePath), [
    "templates/0001/深圳-template.xlsx",
    "templates/0002/广州-template.xlsx",
  ]);
});

test("xiaoxiang template is detected by filename and isolated from normal templates", () => {
  const groups = planPayrollUpload([
    entry("小象-template.xlsx"),
    entry("泉州-template.xlsx"),
  ]);
  assert.deepEqual(groups.map(group => group.mode), ["fengshen", "xiaoxiang"]);
  assert.equal(groups[1].files[0].relativePath, "templates/0001/小象-template.xlsx");
});

test("folder upload uses manual mode with its own source files", () => {
  const groups = planPayrollUpload([
    entry("template.xlsx", "泉州/template.xlsx"),
    entry("配送费.csv", "泉州/配送费.csv"),
    entry("骑手档案.xlsx", "泉州/骑手档案.xlsx"),
  ]);
  assert.deepEqual(groups.map(group => group.mode), ["manual"]);
  assert.deepEqual(groups[0].files.map(file => file.relativePath), [
    "泉州/template.xlsx",
    "泉州/配送费.csv",
    "泉州/骑手档案.xlsx",
  ]);
});

test("mixed folder upload splits xiaoxiang from manual normal templates", () => {
  const groups = planPayrollUpload([
    entry("小象-template.xlsx", "汇总/小象-template.xlsx"),
    entry("泉州-template.xlsx", "汇总/泉州-template.xlsx"),
    entry("配送费.csv", "汇总/配送费.csv"),
  ]);
  assert.deepEqual(groups.map(group => group.mode), ["manual", "xiaoxiang"]);
  assert.deepEqual(groups[0].files.map(file => file.relativePath), [
    "汇总/泉州-template.xlsx",
    "汇总/配送费.csv",
  ]);
  assert.deepEqual(groups[1].files.map(file => file.relativePath), ["templates/0001/小象-template.xlsx"]);
});

test("folder without source files is rejected and empty uploads are rejected", () => {
  assert.throws(() => planPayrollUpload([
    entry("泉州-template.xlsx", "泉州/泉州-template.xlsx"),
  ]), /未找到模板及补充资料源文件/);
  assert.throws(() => planPayrollUpload([entry("说明.txt", "泉州/说明.txt")]), /请上传文件名含 template/);
});