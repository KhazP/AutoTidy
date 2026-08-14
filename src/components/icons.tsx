/**
 * Inline SVG icons. There is no icon dependency and a strict CSP blocks remote
 * assets, so these are hand-rolled 16px glyphs on a 16x16 grid.
 */

interface IconProps {
  size?: number;
  className?: string;
}

function svgProps({ size = 16, className }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.4,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
    className,
  };
}

export const IconPlay = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="M4.5 3.2 12.5 8l-8 4.8V3.2Z" fill="currentColor" stroke="none" />
  </svg>
);

export const IconStop = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <rect x="4" y="4" width="8" height="8" rx="1" fill="currentColor" stroke="none" />
  </svg>
);

export const IconScan = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="M13.5 8a5.5 5.5 0 1 1-1.7-3.97" />
    <path d="M13.6 2.4v3.1h-3.1" />
  </svg>
);

export const IconRefresh = IconScan;

export const IconPlus = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="M8 3.2v9.6M3.2 8h9.6" />
  </svg>
);

export const IconTrash = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="M2.8 4.3h10.4M6.4 4.3V2.9h3.2v1.4M4.2 4.3l.6 8.2h6.4l.6-8.2M6.6 6.6v3.6M9.4 6.6v3.6" />
  </svg>
);

export const IconFolder = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="M1.8 3.6h4.1l1.3 1.6h7v6.9a.6.6 0 0 1-.6.6H2.4a.6.6 0 0 1-.6-.6V3.6Z" />
  </svg>
);

export const IconExternal = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="M9.4 2.6h4v4M13.4 2.6 7.6 8.4" />
    <path d="M12 9.6v3.2a.6.6 0 0 1-.6.6H3.2a.6.6 0 0 1-.6-.6V4.6a.6.6 0 0 1 .6-.6h3.2" />
  </svg>
);

export const IconWarning = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="M8 2.2 15 13.4H1L8 2.2Z" />
    <path d="M8 6.4v3.1M8 11.4v.1" />
  </svg>
);

export const IconInfo = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <circle cx="8" cy="8" r="6.2" />
    <path d="M8 7.2v4M8 4.9v.1" />
  </svg>
);

export const IconSearch = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <circle cx="7.2" cy="7.2" r="4.4" />
    <path d="m10.5 10.5 3 3" />
  </svg>
);

export const IconChevronDown = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="m4 6.2 4 4 4-4" />
  </svg>
);

export const IconChevronRight = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="m6.2 4 4 4-4 4" />
  </svg>
);

export const IconClose = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="m4 4 8 8M12 4l-8 8" />
  </svg>
);

export const IconCheck = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="m3.2 8.4 3.2 3.2 6.4-7.2" />
  </svg>
);

export const IconUndo = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="M3 7.2h6.4a3.4 3.4 0 0 1 0 6.8H6.2" />
    <path d="M5.4 4 2.6 7.2 5.4 10" />
  </svg>
);

export const IconRules = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="M2.6 4h10.8M2.6 8h10.8M2.6 12h6.6" />
  </svg>
);

export const IconHistory = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <circle cx="8" cy="8" r="6" />
    <path d="M8 4.6V8l2.4 1.6" />
  </svg>
);

export const IconSettings = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <circle cx="8" cy="8" r="2.3" />
    <path d="M12.9 9.6a1 1 0 0 0 .2 1.1l.1.1a1.2 1.2 0 1 1-1.7 1.7l-.1-.1a1 1 0 0 0-1.6.7 1.2 1.2 0 1 1-2.4 0v-.1a1 1 0 0 0-1.7-.6l-.1.1a1.2 1.2 0 1 1-1.7-1.7l.1-.1a1 1 0 0 0-.7-1.6 1.2 1.2 0 1 1 0-2.4h.1a1 1 0 0 0 .6-1.7l-.1-.1a1.2 1.2 0 1 1 1.7-1.7l.1.1a1 1 0 0 0 1.6-.7 1.2 1.2 0 1 1 2.4 0v.1a1 1 0 0 0 1.7.6l.1-.1a1.2 1.2 0 1 1 1.7 1.7l-.1.1a1 1 0 0 0 .7 1.6 1.2 1.2 0 1 1 0 2.4h-.1a1 1 0 0 0-.8.6Z" />
  </svg>
);

export const IconEye = (p: IconProps) => (
  <svg {...svgProps(p)}>
    <path d="M1.4 8S3.8 3.6 8 3.6 14.6 8 14.6 8 12.2 12.4 8 12.4 1.4 8 1.4 8Z" />
    <circle cx="8" cy="8" r="1.9" />
  </svg>
);
