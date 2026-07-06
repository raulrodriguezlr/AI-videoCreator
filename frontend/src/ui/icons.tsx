// Inline stroke icons (24×24, currentColor). Icons communicate, not decorate —
// kept to a tight, consistent set.
import type { SVGProps } from "react";

type P = SVGProps<SVGSVGElement>;
const base = (p: P) => ({
  width: 24, height: 24, viewBox: "0 0 24 24", fill: "none",
  stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const, ...p,
});

export const IcFilm = (p: P) => (<svg {...base(p)}><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M17 9h4M3 15h4M17 15h4"/></svg>);
export const IcActivity = (p: P) => (<svg {...base(p)}><path d="M3 12h4l2 7 4-16 2 9h6"/></svg>);
export const IcSliders = (p: P) => (<svg {...base(p)}><path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/></svg>);
export const IcPlus = (p: P) => (<svg {...base(p)}><path d="M12 5v14M5 12h14"/></svg>);
export const IcPlay = (p: P) => (<svg {...base(p)}><path d="M6 4.5 19 12 6 19.5z" fill="currentColor" stroke="none"/></svg>);
export const IcImage = (p: P) => (<svg {...base(p)}><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>);
export const IcMusic = (p: P) => (<svg {...base(p)}><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>);
export const IcWand = (p: P) => (<svg {...base(p)}><path d="m3 21 12-12M15 5l1.5-1.5M19 9l1.5-1.5M14.5 9.5 18 6M9 3l.7 2L12 5.7 9.7 6.4 9 9l-.7-2.6L6 5.7 8.3 5z" /></svg>);
export const IcCpu = (p: P) => (<svg {...base(p)}><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3"/></svg>);
export const IcCloud = (p: P) => (<svg {...base(p)}><path d="M17.5 19a4.5 4.5 0 0 0 .5-9 6 6 0 0 0-11.6-1.5A4 4 0 0 0 6.5 19z"/></svg>);
export const IcCheck = (p: P) => (<svg {...base(p)}><path d="m5 12 5 5L20 6"/></svg>);
export const IcX = (p: P) => (<svg {...base(p)}><path d="M6 6l12 12M18 6 6 18"/></svg>);
export const IcEdit = (p: P) => (<svg {...base(p)}><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>);
export const IcRefresh = (p: P) => (<svg {...base(p)}><path d="M21 12a9 9 0 1 1-2.6-6.4M21 3v6h-6"/></svg>);
export const IcTrash = (p: P) => (<svg {...base(p)}><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>);
export const IcUpload = (p: P) => (<svg {...base(p)}><path d="M12 16V4M7 9l5-5 5 5M5 20h14"/></svg>);
export const IcSparkles = (p: P) => (<svg {...base(p)}><path d="M12 3l1.8 4.7L18.5 9.5 13.8 11.3 12 16l-1.8-4.7L5.5 9.5l4.7-1.8zM19 14l.8 2.2 2.2.8-2.2.8L19 20l-.8-2.2-2.2-.8 2.2-.8z"/></svg>);
export const IcDownload = (p: P) => (<svg {...base(p)}><path d="M12 4v12M7 11l5 5 5-5M5 20h14"/></svg>);
export const IcServer = (p: P) => (<svg {...base(p)}><rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7 7.5h.01M7 16.5h.01"/></svg>);
export const IcChevron = (p: P) => (<svg {...base(p)}><path d="m9 6 6 6-6 6"/></svg>);
export const IcFile = (p: P) => (<svg {...base(p)}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>);
export const IcUsers = (p: P) => (<svg {...base(p)}><circle cx="9" cy="8" r="3.2"/><path d="M3 20a6 6 0 0 1 12 0M16 5.2a3.2 3.2 0 0 1 0 5.6M21 20a6 6 0 0 0-4-5.6"/></svg>);
export const IcList = (p: P) => (<svg {...base(p)}><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>);
export const IcRocket = (p: P) => (<svg {...base(p)}><path d="M5 15c-1.5 1.3-2 5-2 5s3.7-.5 5-2M9 11a5 5 0 0 1 5-5c4 0 6 3 6 3s-1 2-5 6a5 5 0 0 1-5 5M14 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z"/></svg>);
export const IcLayout = (p: P) => (<svg {...base(p)}><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>);
export const IcMessageCircle = (p: P) => (<svg {...base(p)}><path d="M21 12a8 8 0 1 1-3.5-6.6L21 4l-1 4.2A8 8 0 0 1 21 12z"/></svg>);
export const IcArrowRight = (p: P) => (<svg {...base(p)}><path d="M5 12h14M13 5l7 7-7 7"/></svg>);
export const IcGitBranch = (p: P) => (<svg {...base(p)}><circle cx="6" cy="6" r="2.5"/><circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="6" r="2.5"/><path d="M6 8.5v7M8.5 6H14a4 4 0 0 1 4 4v.5"/></svg>);
export const IcSend = (p: P) => (<svg {...base(p)}><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg>);
export const IcRadar = (p: P) => (<svg {...base(p)}><path d="M12 12 19 6"/><path d="M12 12a8 8 0 1 1-5.66-7.66"/><path d="M12 12a4 4 0 1 1-2.83-3.83"/><circle cx="12" cy="12" r="0.6" fill="currentColor"/></svg>);
export const IcCopy = (p: P) => (<svg {...base(p)}><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>);
export const IcAlertTriangle = (p: P) => (<svg {...base(p)}><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/><path d="M12 9v4M12 17h.01"/></svg>);
export const IcLaugh = (p: P) => (<svg {...base(p)}><circle cx="12" cy="12" r="9.5"/><path d="M8 13.5a4.5 4.5 0 0 0 8 0"/><path d="M8.5 9h.01M15.5 9h.01"/></svg>);
export const IcSun = (p: P) => (<svg {...base(p)}><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v3M12 18.5v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2.5 12h3M18.5 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/></svg>);
export const IcMoon = (p: P) => (<svg {...base(p)}><path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/></svg>);
export const IcMenu = (p: P) => (<svg {...base(p)}><path d="M3 6h18M3 12h18M3 18h18"/></svg>);
