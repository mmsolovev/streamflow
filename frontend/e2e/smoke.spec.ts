import { expect, test } from '@playwright/test'

const SECTIONS = [
  { path: '/games', title: 'Игры' },
  { path: '/streams', title: 'Стримы' },
  { path: '/releases', title: 'Релизы' },
  { path: '/recommendations', title: 'Советы' },
  { path: '/hltb', title: 'HowLongToBeat' },
]

/** Видимые строки списка (на узких экранах это карточки, на широких — таблица). */
const visibleRows = (page: import('@playwright/test').Page) =>
  page.locator('[data-row-key]:visible')

test.describe('разделы «Статистики»', () => {
  for (const section of SECTIONS) {
    test(`${section.path}: открывается без ошибок и показывает строки`, async ({
      page,
    }) => {
      const errors: string[] = []
      page.on('pageerror', (error) => errors.push(String(error)))

      await page.goto(section.path)

      await expect(
        page.getByRole('heading', { name: section.title, level: 1 }),
      ).toBeVisible()
      await expect(visibleRows(page).first()).toBeVisible()
      expect(errors).toEqual([])
    })
  }
})

test.describe('фильтры', () => {
  test('в «Играх» фильтр по тегу сужает список', async ({ page }) => {
    await page.goto('/games')
    await expect(visibleRows(page).first()).toBeVisible()
    const before = await visibleRows(page).count()

    await page.getByRole('button', { name: 'Фильтры' }).click()
    // Редкий жанр — в выборке таких игр меньше, чем на странице.
    await page.getByRole('button', { name: /Жанр: TBS/ }).click()

    await expect
      .poll(async () => visibleRows(page).count(), { timeout: 10_000 })
      .toBeLessThan(before)
  })

  test('поиск фильтрует список', async ({ page }) => {
    await page.goto('/games')
    await expect(visibleRows(page).first()).toBeVisible()
    const before = await visibleRows(page).count()

    await page.getByPlaceholder('Поиск игры...').fill('Hades')

    await expect
      .poll(async () => visibleRows(page).count(), { timeout: 10_000 })
      .toBeLessThan(before)
  })
})

test.describe('страница игры', () => {
  test('открывается и показывает название, ссылки и стримы', async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(String(error)))

    await page.goto('/games/1')

    await expect(page.getByRole('heading', { name: 'Страница игры' })).toBeVisible()
    await expect(page.getByRole('link', { name: 'Steam' }).first()).toBeVisible()
    await expect(page.getByRole('link', { name: 'HowLongToBeat' }).first()).toBeVisible()
    await expect(page.getByText(/Стримы \(/)).toBeVisible()
    expect(errors).toEqual([])
  })
})

test.describe('адаптив', () => {
  test('на узком экране список не выходит за границы окна', async ({ page }) => {
    await page.setViewportSize({ width: 480, height: 900 })
    await page.goto('/games')

    await expect(visibleRows(page).first()).toBeVisible()
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    )
    expect(overflow).toBeLessThanOrEqual(1)
  })
})
