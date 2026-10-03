// Strich-Icons aus den Mockups, Farbe über currentColor.
import type { SVGProps } from 'react'

type P = SVGProps<SVGSVGElement> & { size?: number }

const base = (size = 20): SVGProps<SVGSVGElement> => ({
  width: size,
  height: size,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
})

export const IconList = ({ size, ...p }: P) => (
  <svg {...base(size)} {...p}><path d="M4 7h16M4 12h16M4 17h10" /></svg>
)
export const IconTemplate = ({ size, ...p }: P) => (
  <svg {...base(size)} {...p}><path d="M6 3h9l3 3v15H6z" /><path d="M9 10h6M9 14h6M9 18h4" /></svg>
)
export const IconMic = ({ size, ...p }: P) => (
  <svg {...base(size)} {...p}><rect x="8" y="3" width="8" height="12" rx="4" /><path d="M5 11a7 7 0 0014 0M12 18v3" /></svg>
)
export const IconSettings = ({ size, ...p }: P) => (
  <svg {...base(size)} {...p}><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1" /></svg>
)
export const IconFolder = ({ size, ...p }: P) => (
  <svg {...base(size ?? 18)} {...p}><path d="M3 6h6l2 2h10v11H3z" /></svg>
)
export const IconInbox = ({ size, ...p }: P) => (
  <svg {...base(size ?? 18)} {...p}><path d="M4 4h16v16H4zM4 9h16" /></svg>
)
export const IconTrash = ({ size, ...p }: P) => (
  <svg {...base(size ?? 18)} {...p}><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" /></svg>
)
export const IconPlus = ({ size, ...p }: P) => (
  <svg {...base(size ?? 18)} {...p}><path d="M12 5v14M5 12h14" /></svg>
)
export const IconSearch = ({ size, ...p }: P) => (
  <svg {...base(size ?? 16)} {...p}><circle cx="11" cy="11" r="7" /><path d="M20 20l-4-4" /></svg>
)
export const IconMoon = ({ size, ...p }: P) => (
  <svg {...base(size ?? 18)} {...p}><path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z" /></svg>
)
export const IconStar = ({ size, filled, ...p }: P & { filled?: boolean }) => (
  <svg {...base(size ?? 16)} fill={filled ? 'currentColor' : 'none'} {...p}><path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z" /></svg>
)
export const IconRestore = ({ size, ...p }: P) => (
  <svg {...base(size ?? 16)} {...p}><path d="M4 12a8 8 0 108-8H8" /><path d="M10 1L7 4l3 3" /></svg>
)
export const IconSpark = ({ size, ...p }: P) => (
  <svg {...base(size ?? 16)} {...p}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /></svg>
)
export const IconUpload = ({ size, ...p }: P) => (
  <svg {...base(size ?? 16)} {...p}><path d="M12 15V3M7 8l5-5 5 5M5 14v5a2 2 0 002 2h10a2 2 0 002-2v-5" /></svg>
)
export const IconPlay = ({ size, ...p }: P) => (
  <svg {...base(size ?? 18)} fill="currentColor" stroke="none" {...p}><path d="M8 5l11 7-11 7z" /></svg>
)
export const IconPause = ({ size, ...p }: P) => (
  <svg {...base(size ?? 18)} fill="currentColor" stroke="none" {...p}><rect x="6" y="5" width="4" height="14" rx="1" /><rect x="14" y="5" width="4" height="14" rx="1" /></svg>
)
