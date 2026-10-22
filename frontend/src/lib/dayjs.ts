import dayjs from 'dayjs'
import 'dayjs/locale/ru'
import utc from 'dayjs/plugin/utc'

// Даты с бэкенда — naive UTC; utc-плагин нужен для корректного .local().
dayjs.extend(utc)
dayjs.locale('ru')

export { dayjs }
