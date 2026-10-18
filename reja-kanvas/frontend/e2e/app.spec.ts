import { expect, test } from "@playwright/test";
import { login, quickAdd, register, totp, uniqueEmail, watchErrors } from "./helpers";

test("first run: empty canvas, template, cards appear", async ({ page }) => {
  const errors = watchErrors(page);
  await register(page, "Ali", uniqueEmail("ali"));
  await expect(page.getByRole("heading", { name: "Birinchi rejangizni tuzing" })).toBeVisible();
  await page.getByRole("button", { name: /Talaba/ }).click();
  await expect(page.getByRole("article", { name: /Reja: Uy vazifasi/ })).toBeVisible();
  await expect(page.getByRole("article")).toHaveCount(4);
  expect(errors).toEqual([]);
});

test("quick add understands Uzbek and the plan can be finished and undone", async ({ page }) => {
  const errors = watchErrors(page);
  await register(page, "Vali", uniqueEmail("vali"));
  await quickAdd(page, "ertaga 15:00 Mijoz bilan uchrashuv #ish !yuqori");
  const card = page.getByRole("article", { name: "Reja: Mijoz bilan uchrashuv" });
  await expect(card).toBeVisible();
  await expect(card.getByText("Yuqori")).toBeVisible();
  await expect(card.getByText("ish", { exact: true })).toBeVisible();

  await page.getByRole("link", { name: "Ro'yxat" }).click();
  await page.getByRole("link", { name: /Mijoz bilan uchrashuv/ }).click();
  await expect(page.getByRole("heading", { name: "Bajarilishni tasdiqlash" })).toBeVisible();

  const stepInput = page.getByPlaceholder("Bosqich qo'shing va Enter bosing…");
  await stepInput.fill("Taqdimot");
  await stepInput.press("Enter");
  await stepInput.fill("Shartnoma");
  await stepInput.press("Enter");
  const submit = page.getByRole("button", { name: "Tasdiqlash va yakunlash" });
  await expect(submit).toBeDisabled();
  await page.getByRole("checkbox", { name: "Taqdimot" }).check();
  await page.getByRole("checkbox", { name: "Shartnoma" }).check();
  await expect(submit).toBeEnabled();
  await submit.click();
  await expect(page.getByText("Tasdiqlandi ·")).toBeVisible();

  await page.getByRole("status").filter({ hasText: "Reja bajarildi!" }).getByRole("button", { name: "Bekor qilish" }).click();
  await expect(page.getByText("Tasdiq bekor qilindi")).toBeVisible();
  await expect(page.getByRole("button", { name: "Tasdiqlash va yakunlash" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("approval: approver returns the plan with a reason", async ({ browser }) => {
  const approverEmail = uniqueEmail("aziza");
  const boss = await browser.newContext();
  const bossPage = await boss.newPage();
  await register(bossPage, "Aziza", approverEmail);

  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errors = watchErrors(page);
  await register(page, "Bobur", uniqueEmail("bobur"));
  await quickAdd(page, "Choraklik hisobot");
  await page.getByRole("link", { name: "Ro'yxat" }).click();
  await page.getByRole("link", { name: /Choraklik hisobot/ }).click();
  await page.getByPlaceholder("Hamkasb pochtasi").first().fill(approverEmail);
  await page.getByRole("button", { name: "Qo'shish" }).first().click();
  await expect(page.getByText("Aziza", { exact: true }).first()).toBeVisible();
  await page.waitForTimeout(1500); // let the change reach the server
  await page.getByRole("button", { name: "Tasdiqlashga yuborish" }).click();
  await expect(page.getByText("TASDIQ KUTILMOQDA")).toBeVisible();

  await bossPage.goto("/inbox");
  await bossPage.getByRole("link", { name: /Choraklik hisobot/ }).first().click();
  await bossPage.getByRole("button", { name: "Qaytarish" }).click();
  await bossPage.getByLabel("Nima uchun qaytaryapsiz?").fill("Raqamlar eskirgan");
  await bossPage.getByRole("button", { name: "Qaytarish" }).click();
  await expect(bossPage.getByText("Faol").or(bossPage.getByText("Qaytarildi")).first()).toBeVisible();

  await page.reload();
  await expect(page.getByRole("alert").filter({ hasText: "Reja qaytarildi" })).toBeVisible();
  await expect(page.getByText("«Raqamlar eskirgan»")).toBeVisible();
  expect(errors).toEqual([]);
  await boss.close();
  await ctx.close();
});

test("offline: edits are queued and sent when the connection returns", async ({ page, context }) => {
  await register(page, "Gulnoza", uniqueEmail("gul"));
  await page.getByRole("button", { name: "Bo'sh kartadan boshlash" }).click();
  const title = page.getByRole("textbox", { name: "Nomini o'zgartirish" });
  await title.fill("Oflayn reja");
  await title.press("Enter");
  await page.waitForTimeout(1500);
  await context.setOffline(true);
  await page.evaluate(() => window.dispatchEvent(new Event("offline")));
  await expect(page.getByText("Oflayn rejim")).toBeVisible();
  const card = page.getByRole("article", { name: "Reja: Oflayn reja" });
  await card.focus();
  await page.keyboard.press("F2");
  const edit = page.getByRole("textbox", { name: "Nomini o'zgartirish" });
  await edit.fill("Oflayn tahrir");
  await edit.press("Enter");
  await expect(page.getByText(/ta o'zgarish navbatda/)).toBeVisible();
  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect(page.getByText("Oflayn rejim")).toBeHidden({ timeout: 20_000 });
  await page.reload();
  await expect(page.getByRole("article", { name: "Reja: Oflayn tahrir" })).toBeVisible();
});

test("two-step sign-in", async ({ page }) => {
  const email = uniqueEmail("totp");
  await register(page, "Sardor", email);
  await page.goto("/settings");
  await page.getByRole("button", { name: "Sozlash" }).click();
  const secret = (await page.locator("code").first().innerText()).replace(/\s/g, "");
  await page.getByLabel("Tasdiqlash kodi").fill(totp(secret));
  await page.getByRole("button", { name: "Kodni tasdiqlash va yoqish" }).click();
  await expect(page.getByText(/Zaxira kodlar/)).toBeVisible();
  await page.getByRole("button", { name: "Profil menyusi" }).click();
  await page.getByRole("button", { name: "Chiqish" }).click();
  await expect(page).toHaveURL(/\/login/);
  await login(page, email, "parol12345", totp(secret));
  await expect(page).toHaveURL(/\/canvas/);
});

test("every page opens without errors, dark mode applies", async ({ page }) => {
  const errors = watchErrors(page);
  await register(page, "Dilshod", uniqueEmail("dil"));
  await quickAdd(page, "bugun 18:00 Sport zal #sog'liq");
  const pages: [string, RegExp][] = [
    ["/list", /Bugun/],
    ["/kanban", /Doska/],
    ["/calendar", /\d{4}/],
    ["/goals", /Maqsadlar/],
    ["/review", /Haftalik sharh/],
    ["/analytics", /Tahlil/],
    ["/teams", /Jamoalar/],
    ["/inbox", /Kiruvchi/],
    ["/trash", /Savatcha/],
    ["/settings", /Sozlamalar/],
  ];
  for (const [path, heading] of pages) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading }).first()).toBeVisible();
  }
  await page.goto("/settings");
  await page.getByRole("radio", { name: "Tungi" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.goto("/canvas");
  await expect(page.locator("html")).toHaveClass(/dark/);
  expect(errors).toEqual([]);
});

test("teams: a member sees the shared board's plans", async ({ browser }) => {
  const memberEmail = uniqueEmail("member");
  const m = await browser.newContext();
  const mp = await m.newPage();
  await register(mp, "Jasur", memberEmail);

  const o = await browser.newContext();
  const op = await o.newPage();
  await register(op, "Nodira", uniqueEmail("owner"));
  await op.goto("/teams");
  await op.getByPlaceholder("Jamoa nomi").fill("Sotuv");
  await op.getByRole("button", { name: "Jamoa yaratish" }).click();
  await op.getByPlaceholder("Hamkasb pochtasi").fill(memberEmail);
  await op.getByRole("button", { name: "A'zo qo'shish" }).click();
  await expect(op.getByText("Jasur")).toBeVisible();
  await op.getByRole("button", { name: /Doskani ochish/ }).click();
  await expect(op).toHaveURL(/\/canvas/);
  await quickAdd(op, "Jamoa rejasi");
  await op.waitForTimeout(1500);

  await mp.goto("/canvas");
  await mp.getByLabel("Doskani tanlash").selectOption({ label: "Jamoa: Sotuv · Sotuv" });
  await expect(mp.getByRole("article", { name: "Reja: Jamoa rejasi" })).toBeVisible();
  await m.close();
  await o.close();
});
