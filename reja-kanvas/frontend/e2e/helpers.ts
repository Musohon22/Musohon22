import { createHmac } from "node:crypto";
import { expect, type Page } from "@playwright/test";

let n = 0;
export function uniqueEmail(prefix: string) {
  n += 1;
  return `${prefix}.${Date.now()}.${n}@example.com`;
}

/** Fails the test on any uncaught exception in the page. */
export function watchErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  return errors;
}

export async function register(page: Page, name: string, email: string, password = "parol12345") {
  await page.goto("/login");
  await page.getByRole("tab", { name: "Ro'yxatdan o'tish" }).click();
  await page.getByLabel("Ismingiz").fill(name);
  await page.getByLabel("Elektron pochta").fill(email);
  await page.getByLabel("Parol").fill(password);
  await page.getByRole("button", { name: "Hisob yaratish" }).click();
  await expect(page).toHaveURL(/\/canvas/);
  await skipTour(page);
}

export async function skipTour(page: Page) {
  const skip = page.getByRole("button", { name: "O'tkazib yuborish" });
  await skip.waitFor({ timeout: 8000 }).catch(() => undefined);
  if (await skip.isVisible().catch(() => false)) await skip.click();
}

export async function login(page: Page, email: string, password = "parol12345", code?: string) {
  await page.goto("/login");
  await page.getByLabel("Elektron pochta").fill(email);
  await page.getByLabel("Parol").fill(password);
  await page.getByRole("button", { name: "Kirish", exact: true }).last().click();
  if (code) {
    await page.getByLabel("Tasdiqlash kodi").fill(code);
    await page.getByRole("button", { name: "Kirish", exact: true }).last().click();
  }
}

export async function quickAdd(page: Page, text: string) {
  await page.keyboard.press("Control+k");
  const box = page.getByPlaceholder(/Reja yozing yoki qidiring/);
  await box.fill(text);
  await page.waitForTimeout(700); // server-side parsing preview
  await box.press("Enter");
  await expect(page.getByText("Reja yaratildi")).toBeVisible();
}

/** RFC 6238 TOTP, same as the server, to complete two-step sign-in in tests. */
export function totp(secretB32: string, at = Date.now()) {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  let bits = "";
  for (const c of secretB32.replace(/=+$/, "")) bits += alphabet.indexOf(c).toString(2).padStart(5, "0");
  const key = Buffer.from(bits.match(/.{8}/g)!.map((b) => parseInt(b, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(at / 1000 / 30)));
  const h = createHmac("sha1", key).update(counter).digest();
  const o = h[h.length - 1] & 0xf;
  return String((h.readUInt32BE(o) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}
