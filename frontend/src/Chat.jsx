import { useEffect, useRef, useState } from "react";
import { sendMessage } from "./api";

export default function Chat({ messages, setMessages, loading, setLoading, onPlan }) {
  const [text, setText] = useState("");
  const logRef = useRef(null);
  const inputRef = useRef(null);

  useEffect(() => {
    const log = logRef.current;
    if (log) log.scrollTop = log.scrollHeight;
    if (!loading) inputRef.current?.focus();
  }, [messages, loading]);

  async function submit(event) {
    event.preventDefault();
    const message = text.trim();
    if (!message || loading) return;

    setMessages((log) => [...log, { role: "user", text: message }]);
    setText("");
    setLoading(true);
    try {
      const answer = await sendMessage(message);
      setMessages((log) => [...log, { role: "assistant", text: answer.reply }]);
      onPlan(answer.plan);
    } catch (error) {
      setMessages((log) => [...log, { role: "error", text: error.message }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <aside className="chat">
      <div className="chat-log" ref={logRef}>
        {messages.map((message, index) => (
          <div key={index} className={`chat-message ${message.role}`}>{message.text}</div>
        ))}
        {loading && <div className="chat-message">Думаю…</div>}
      </div>
      <form className="chat-form" onSubmit={submit}>
        <input
          ref={inputRef}
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Перенеси задачи Иванова на неделю вправо"
          disabled={loading}
        />
        <button type="submit" disabled={loading || !text.trim()}>Отправить</button>
      </form>
    </aside>
  );
}
