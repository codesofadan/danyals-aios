import SourceMonitor from "./SourceMonitor";
import ChangeFeed from "./ChangeFeed";
import KnowledgeBase from "./KnowledgeBase";
import Recommendations from "./Recommendations";

export default function PolicyWorkspace() {
  return (
    <div className="pr-wrap">
      <div className="pr-loop">
        <span className="pr-loop-t"><span className="material-symbols-rounded">all_inclusive</span>Closed loop</span>
        {["Watch", "Detect", "Research", "Flag", "Recommend", "Confirm"].map((s, i) => (
          <span className="pr-loop-step" key={s}>
            <span className="pr-loop-n">{i + 1}</span>{s}
          </span>
        ))}
      </div>

      <div className="row b">
        <SourceMonitor />
        <ChangeFeed />
      </div>

      <div className="row-single">
        <KnowledgeBase />
      </div>

      <div className="row-single">
        <Recommendations />
      </div>
    </div>
  );
}
