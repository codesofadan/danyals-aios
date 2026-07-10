"use client";

import { useState } from "react";
import {
  contentJobs, clientAccent,
  type ContentJob, type Framework,
} from "@/lib/content";
import ContentKpis from "./ContentKpis";
import PipelineBoard from "./PipelineBoard";
import ReviewGate, { type ReviewAction } from "./ReviewGate";
import NewJobForm, { type NewJob } from "./NewJobForm";
import Frameworks from "./Frameworks";

let seq = 0;
const nextId = () => `CJ-${4200 + seq++}`;

// Auto framework pick: page type + intent heuristic (mirrors the selector stage).
function autoFramework(pageType: NewJob["pageType"]): Framework {
  if (pageType === "service") return "AIDA";
  if (pageType === "local") return "BAB";
  return "PAS";
}
const schemaFor = (pageType: NewJob["pageType"]) =>
  pageType === "service" ? "Service" : pageType === "local" ? "LocalBusiness" : "Article";

export default function ContentWorkspace() {
  const [jobs, setJobs] = useState<ContentJob[]>(contentJobs);

  function handleCreate(input: NewJob) {
    const resolved = input.framework === "Auto" ? autoFramework(input.pageType) : input.framework;
    const job: ContentJob = {
      id: nextId(),
      client: input.client,
      color: clientAccent(input.client),
      pageType: input.pageType,
      topic: input.topic,
      framework: resolved,
      auto: input.framework === "Auto",
      target: input.target,
      status: "queued",
      cost: 0,
      words: 0,
      schema: schemaFor(input.pageType),
      images: 0,
      stage: "Queued",
      ago: "just now",
    };
    setJobs((prev) => [job, ...prev]);
  }

  function handleReview(id: string, action: ReviewAction) {
    setJobs((prev) => prev.map((j) => {
      if (j.id !== id) return j;
      if (action === "approve") return { ...j, status: "publishing", stage: "Publish", ago: "just now" };
      if (action === "edit") return { ...j, status: "drafting", stage: "Draft", ago: "just now" };
      return { ...j, status: "rejected", stage: "Rejected", ago: "just now" };
    }));
    // approve → auto-advance from publishing to done, like the WordPress push finishing.
    if (action === "approve") {
      setTimeout(() => {
        setJobs((prev) => prev.map((j) =>
          j.id === id && j.status === "publishing"
            ? { ...j, status: "done", stage: "Published", ago: "just now" }
            : j));
      }, 1400);
    }
  }

  const needsReview = jobs.filter((j) => j.status === "needs_review");

  return (
    <>
      <ContentKpis jobs={jobs} />

      <PipelineBoard jobs={jobs} />

      <div className="row">
        <ReviewGate jobs={needsReview} onAction={handleReview} />
        <NewJobForm onCreate={handleCreate} />
      </div>

      <div className="row-single">
        <Frameworks />
      </div>
    </>
  );
}
