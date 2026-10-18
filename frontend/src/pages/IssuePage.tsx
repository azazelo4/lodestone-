import { useNavigate, useParams } from "react-router-dom";
import { IssueBody } from "../components/IssuePanel";
import { StateDot } from "../components/bits";
import { useT } from "../i18n";

export default function IssuePage() {
  const { issueKey = "" } = useParams();
  const nav = useNavigate();
  const { t } = useT();
  const project = issueKey.split("-")[0];
  return (
    <div className="content" style={{ background: "var(--surface)" }}>
      <IssueBody issueKey={issueKey.toUpperCase()} onOpen={(k) => nav(`/i/${k}`)} onDeleted={() => nav(`/p/${project}`)}
                 header={(issue, a) => (
                   <div className="panel-head">
                     <a className="btn ghost sm" href={`/p/${project}`} onClick={(e) => { e.preventDefault(); nav(`/p/${project}`); }}>← {project}</a>
                     {issue && <StateDot category={issue.state.category} />}
                     <span className="key">{issueKey.toUpperCase()}</span>
                     <span style={{ flex: 1 }} />
                     <button className="btn ghost sm" onClick={a.copy}>{t("issue.copyLink")}</button>
                     {a.canDelete && <button className="btn ghost sm danger" onClick={a.remove}>{t("issue.delete")}</button>}
                   </div>
                 )} />
    </div>
  );
}
