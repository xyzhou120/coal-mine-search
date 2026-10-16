import dayjs from 'dayjs'
export const fmtTime = t => t ? dayjs(t).format('YYYY-MM-DD HH:mm:ss') : '—'
