"use client";

import AskBox from "./AskBox";
import ChangeFeed from "./ChangeFeed";
import Recommendations from "./Recommendations";

export default function PolicyWorkspace() {
  return (
    <div className="pr-wrap">
      <div className="row-single">
        <AskBox />
      </div>

      <div className="row-single">
        <Recommendations />
      </div>

      <div className="row-single">
        <ChangeFeed />
      </div>
    </div>
  );
}
