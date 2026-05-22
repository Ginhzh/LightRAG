use anyhow::Result;

#[tokio::main]
async fn main() -> Result<()> {
    retrieval_harness::cli::run().await
}
