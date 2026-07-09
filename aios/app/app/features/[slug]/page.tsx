import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import TopBar from "@/components/TopBar";
import { allFeatureSlugs, getFeature, neighbors, TIER_LABEL } from "@/lib/features";

type Params = { params: { slug: string } };

export function generateStaticParams() {
  return allFeatureSlugs().map((slug) => ({ slug }));
}

export function generateMetadata({ params }: Params): Metadata {
  const found = getFeature(params.slug);
  if (!found) return { title: "Feature · AIOS" };
  return { title: `${found.feature.name} · AIOS`, description: found.feature.blurb };
}

export default function FeaturePage({ params }: Params) {
  const found = getFeature(params.slug);
  if (!found) notFound();
  const { feature, module } = found;
  const related = module.features.filter((f) => f.slug !== feature.slug);
  const { prev, next } = neighbors(feature.slug);

  return (
    <>
      <TopBar
        eyebrow={`Module ${module.num} · ${module.name}`}
        title={feature.name}
        searchPlaceholder="Search features…"
      />

      <nav className="feat-crumbs" aria-label="Breadcrumb">
        <Link href="/">Command Center</Link>
        <span>/</span>
        <Link href="/features">Features</Link>
        <span>/</span>
        <b>{feature.name}</b>
      </nav>

      <section className="card feat-hero">
        <span className="feat-medallion">
          <span className="material-symbols-rounded">{feature.icon}</span>
        </span>
        <div>
          <div className="feat-tags">
            <span className={`ftier ${feature.tier}`}>{TIER_LABEL[feature.tier]}</span>
            <span className="mod-badge">Module {module.num} · {module.name}</span>
          </div>
          <h2>{feature.name}</h2>
          <p>{feature.blurb}</p>
        </div>
      </section>

      <div className="row b">
        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">What it does</div>
              <div className="cs">The capability, in detail</div>
            </div>
          </div>
          <ul className="feat-detail">
            {feature.details.map((d, i) => (
              <li key={i}>{d}</li>
            ))}
          </ul>
        </section>

        <section className="card">
          <div className="card-h">
            <div>
              <div className="ct">Where it fits</div>
              <div className="cs">{module.tagline}</div>
            </div>
          </div>
          <p className="feat-context">{module.context}</p>
          <div className="feat-note">
            <span className="material-symbols-rounded">verified</span>
            A person approves anything client-facing before it ships — automation removes the manual work, never the approval.
          </div>
        </section>
      </div>

      <section className="card">
        <div className="card-h">
          <div>
            <div className="ct">More in {module.name}</div>
            <div className="cs">Related capabilities in this module</div>
          </div>
        </div>
        <div className="feat-related">
          {related.map((f) => (
            <Link key={f.slug} href={`/features/${f.slug}`} className="feat-bubble">
              <span className="medallion">
                <span className="material-symbols-rounded">{f.icon}</span>
              </span>
              <span className="blab">{f.label}</span>
              <span className={`tdot ${f.tier}`} aria-hidden="true" />
            </Link>
          ))}
        </div>
      </section>

      <nav className="feat-prevnext">
        {prev ? (
          <Link href={`/features/${prev.slug}`} className="pn prev">
            <span className="material-symbols-rounded">arrow_back</span>
            <span><span className="pn-k">Previous</span><span className="pn-n">{prev.name}</span></span>
          </Link>
        ) : <span />}
        {next ? (
          <Link href={`/features/${next.slug}`} className="pn next">
            <span><span className="pn-k">Next</span><span className="pn-n">{next.name}</span></span>
            <span className="material-symbols-rounded">arrow_forward</span>
          </Link>
        ) : <span />}
      </nav>
    </>
  );
}
