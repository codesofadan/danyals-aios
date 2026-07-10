type Props = { eyebrow: string; title: string; searchPlaceholder?: string };

export default function TopBar({ eyebrow, title, searchPlaceholder = "Search…" }: Props) {
  return (
    <div className="topbar">
      <div className="tt">
        <div className="ey">{eyebrow}</div>
        <h1>{title}</h1>
      </div>
      <div className="topbar-actions">
        <label className="search">
          <span className="material-symbols-rounded" style={{ fontSize: 20 }}>search</span>
          <input placeholder={searchPlaceholder} />
        </label>
        <div className="iconbtn">
          <span className="material-symbols-rounded">notifications</span>
          <span className="dot" />
        </div>
        <div className="iconbtn">
          <span className="material-symbols-rounded">add</span>
        </div>
      </div>
    </div>
  );
}
